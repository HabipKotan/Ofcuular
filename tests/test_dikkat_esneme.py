"""Esneme cezasi ve skor mantigi (kamera gerektirmez): python -m pytest tests/test_dikkat_esneme.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sensing.focus.classroom_focus import Esikler, OlayDedektoru, esneme_carpani, yuz_olc  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

E = Esikler()


def test_konusma_cezasiz():
    # Konusurken agiz acikligi ~0.1-0.4: skor dusmemeli
    for cene in (0.0, 0.2, 0.4, 0.5):
        assert yuz_olc(0, 0, 0.0, cene, E).skor == 100.0


def test_esneme_dikkatsiz_sayilir():
    o = yuz_olc(0, 0, 0.0, 0.85, E)        # tahtaya bakiyor, gozler acik, ama esniyor
    assert o.esniyor and o.skor < E.dikkatsiz_esik
    assert round(o.skor) == 35


def test_rampa_kademeli():
    a, b, c = (esneme_carpani(x, E) for x in (0.55, 0.65, 0.75))
    assert 1.0 > a > b > c > E.esneme_tabani


def test_not_alirken_esneyen_de_ceza_alir():
    deftere = yuz_olc(0, 30, 0.0, 0.0, E).skor      # bas egik, goz acik -> taban puan 60
    esneyerek = yuz_olc(0, 30, 0.0, 0.9, E).skor
    assert deftere == 60.0 and esneyerek < deftere * 0.5


def test_ceza_kapatilabilir():
    assert yuz_olc(0, 0, 0.0, 0.9, E, esneme_cezasi=False).skor == 100.0


def test_olay_nedeni_esneme():
    d = OlayDedektoru(esik=50, min_sure=10)
    t = datetime(2026, 10, 10, 9, 0, 0)
    for i in range(4):
        d.besle(t + timedelta(seconds=5 * i), t + timedelta(seconds=5 * i + 5), 30.0,
                {"yana": 0.0, "egik": 0.05, "kapali": 0.1, "esneme": 0.6})
    olay = d.kapat()
    assert olay is not None and olay.neden == "esneme / uyku hali"
