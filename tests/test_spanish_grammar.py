"""Spanish gender / person slip detectors."""
from core import language as lang


def test_self_masculine_flagged():
    assert lang.looks_broken_spanish("ay baby estoy mojado pensando en ti")
    assert lang.looks_broken_spanish("me tiene mojado y no puedo más")
    assert not lang.looks_broken_spanish("estoy mojada pensando en tu polla")


def test_call_him_feminine_flagged():
    assert lang.looks_broken_spanish("ay guapa, ven aquí")
    assert lang.looks_broken_spanish("eres muy hermosa hoy")
    assert not lang.looks_broken_spanish("ay guapo, ven aquí")


def test_broken_person_flagged():
    assert lang.looks_broken_spanish("tú estoy loca por ti")
    assert lang.looks_broken_spanish("estoy getting wet baby")
    assert not lang.looks_broken_spanish("tú me tienes loca")


if __name__ == "__main__":
    test_self_masculine_flagged()
    test_call_him_feminine_flagged()
    test_broken_person_flagged()
    print("ok")
