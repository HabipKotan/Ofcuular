"""
MediaPipe ile Gerçek Zamanlı Odak Kaynağı (Edge AI & Zero-Storage)
==================================================================
Kameradan alınan kareler YALNIZCA yerel bellekte (RAM) işlenir.
Diske hiçbir kare, fotoğraf veya video kaydedilmez (Zero-Storage).
Yüz tanıma / kimlik tespiti yapılmaz; yalnızca 468 yüz landmark'ı
üzerinden soyut bir 'Odak Skoru' (0-100) hesaplanır ve kare anında yok edilir.

Hesaplanan Metrikler:
1. Baş Açısı (Head Pose): Pitch (aşağı/yukarı) ve Yaw (sağa/sola) açısı.
2. Göz Açıklığı (EAR - Eye Aspect Ratio): Göz kırpma ve uyuklama tespiti.
"""

from __future__ import annotations

import time
from typing import Iterator, Optional, Tuple
import numpy as np

from core.schemas import FocusSample
from sensing.focus.base import FocusSource

# 3D Model Referans Noktaları (Kanonik Yüz Modeli)
MODEL_POINTS = np.array([
    (0.0, 0.0, 0.0),          # Burun ucu (landmark 1)
    (0.0, -330.0, -65.0),     # Çene (landmark 152)
    (-225.0, 170.0, -135.0),  # Sol göz sol köşesi (landmark 33)
    (225.0, 170.0, -135.0),   # Sağ göz sağ köşesi (landmark 263)
    (-150.0, -150.0, -125.0), # Sol ağız köşesi (landmark 61)
    (150.0, -150.0, -125.0),  # Sağ ağız köşesi (landmark 291)
], dtype=np.float64)

# Göz Landmark İndeksleri (EAR hesabı için)
LEFT_EYE_IDXS = [362, 385, 387, 263, 373, 380]
RIGHT_EYE_IDXS = [33, 160, 158, 133, 153, 144]


class EdgeMediaPipeFocusSource(FocusSource):
    """
    Yerel web kamerası üzerinden canlı odak ölçümü yapan kaynak.
    """

    def __init__(
        self,
        camera_index: int = 0,
        sample_rate_hz: float = 2.0,
        max_duration_s: Optional[float] = None,
    ):
        self.camera_index = camera_index
        self.sample_rate_hz = sample_rate_hz
        self.max_duration_s = max_duration_s
        self._delay = 1.0 / max(0.1, sample_rate_hz)

    @staticmethod
    def _calculate_ear(landmarks, eye_indices, img_w: int, img_h: int) -> float:
        """Eye Aspect Ratio (Göz Açıklık Oranı) hesaplar."""
        pts = np.array([
            [landmarks[idx].x * img_w, landmarks[idx].y * img_h]
            for idx in eye_indices
        ])
        # Dikey mesafeler
        d_v1 = np.linalg.norm(pts[1] - pts[5])
        d_v2 = np.linalg.norm(pts[2] - pts[4])
        # Yatay mesafe
        d_h = np.linalg.norm(pts[0] - pts[3])
        if d_h < 1e-6:
            return 0.0
        return float((d_v1 + d_v2) / (2.0 * d_h))

    @staticmethod
    def _estimate_head_pose(landmarks, img_w: int, img_h: int, cv2) -> Tuple[float, float, float]:
        """PnP algoritması ile Pitch, Yaw, Roll açılarını derece olarak hesaplar."""
        image_points = np.array([
            (landmarks[1].x * img_w, landmarks[1].y * img_h),
            (landmarks[152].x * img_w, landmarks[152].y * img_h),
            (landmarks[33].x * img_w, landmarks[33].y * img_h),
            (landmarks[263].x * img_w, landmarks[263].y * img_h),
            (landmarks[61].x * img_w, landmarks[61].y * img_h),
            (landmarks[291].x * img_w, landmarks[291].y * img_h),
        ], dtype=np.float64)

        focal_length = img_w
        center = (img_w / 2.0, img_h / 2.0)
        camera_matrix = np.array(
            [[focal_length, 0, center[0]],
             [0, focal_length, center[1]],
             [0, 0, 1]], dtype=np.float64
        )
        dist_coeffs = np.zeros((4, 1))

        success, rotation_vector, _ = cv2.solvePnP(
            MODEL_POINTS, image_points, camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE
        )
        if not success:
            return 0.0, 0.0, 0.0

        rotation_mat, _ = cv2.Rodrigues(rotation_vector)
        # Euler açılarına dönüşüm
        sy = np.sqrt(rotation_mat[0, 0] ** 2 + rotation_mat[1, 0] ** 2)
        if sy > 1e-6:
            pitch = np.arctan2(rotation_mat[2, 1], rotation_mat[2, 2])
            yaw = np.arctan2(-rotation_mat[2, 0], sy)
            roll = np.arctan2(rotation_mat[1, 0], rotation_mat[0, 0])
        else:
            pitch = np.arctan2(-rotation_mat[1, 2], rotation_mat[1, 1])
            yaw = np.arctan2(-rotation_mat[2, 0], sy)
            roll = 0.0

        return np.degrees(pitch), np.degrees(yaw), np.degrees(roll)

    def stream(self) -> Iterator[FocusSample]:
        """
        Kamera akışından Zero-Storage kuralıyla odak serisi üretir.
        """
        try:
            import cv2
            import mediapipe as mp
        except ImportError as e:
            raise RuntimeError(
                f"Edge AI modülü için 'opencv-python' ve 'mediapipe' paketleri gereklidir: {e}"
            )

        mp_face_mesh = mp.solutions.face_mesh
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            raise RuntimeError(f"Webcam ({self.camera_index}) açılamadı.")

        start_time = time.time()
        
        with mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        ) as face_mesh:
            try:
                while cap.isOpened():
                    now = time.time()
                    elapsed = now - start_time
                    if self.max_duration_s and elapsed > self.max_duration_s:
                        break

                    ret, frame = cap.read()
                    if not ret:
                        break

                    h, w, _ = frame.shape
                    # BGR -> RGB (RAM içi)
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = face_mesh.process(rgb_frame)

                    # --- ZERO-STORAGE: Ham kare bellekten derhal serbest bırakılır ---
                    del frame
                    del rgb_frame

                    if not results.multi_face_landmarks:
                        # Ekranda yüz yoksa odak skoru = 10
                        yield FocusSample(timestamp=round(elapsed, 2), focus_score=10.0)
                    else:
                        landmarks = results.multi_face_landmarks[0].landmark

                        # 1. Baş açısı cezası
                        pitch, yaw, _ = self._estimate_head_pose(landmarks, w, h, cv2)
                        head_deviation = np.sqrt(pitch**2 + (yaw * 1.2)**2)
                        # Normal bakış ~ 15 derece sapma toleransı
                        pose_score = np.clip(100.0 - (head_deviation - 15.0) * 2.5, 0.0, 100.0)

                        # 2. Göz açıklık oranı (EAR)
                        left_ear = self._calculate_ear(landmarks, LEFT_EYE_IDXS, w, h)
                        right_ear = self._calculate_ear(landmarks, RIGHT_EYE_IDXS, w, h)
                        avg_ear = (left_ear + right_ear) / 2.0
                        # 0.22 üstü açık göz, 0.16 altı kapalı
                        ear_score = np.clip((avg_ear - 0.16) / (0.26 - 0.16) * 100.0, 0.0, 100.0)

                        # Bileşik Odak Skoru: %65 Baş Açısı + %35 Göz Açıklığı
                        combined = 0.65 * pose_score + 0.35 * ear_score
                        final_score = float(np.clip(combined, 0.0, 100.0))

                        yield FocusSample(
                            timestamp=round(elapsed, 2),
                            focus_score=round(final_score, 1),
                        )

                    time.sleep(self._delay)

            finally:
                cap.release()