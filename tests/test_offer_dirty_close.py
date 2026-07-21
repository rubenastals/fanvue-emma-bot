"""Max-dirty from Emma promise + owed-send close (no beg loop / no L2 bait)."""
from core.offer_selector import (
    context_wants_max_dirty,
    emma_owed_send,
    wants_max_dirty,
)


def test_como_de_guarra_is_max_dirty():
    assert wants_max_dirty("te pregunto que como de guarra es tu foto")


def test_emma_promise_plus_ensenamela():
    history = [
        {
            "role": "assistant",
            "content": (
                "la más guarra, baby... esa es la que me hice tocándome "
                "pensando en tu polla hasta gemir tu nombre"
            ),
        }
    ]
    assert context_wants_max_dirty("enseñamela", history)
    assert not context_wants_max_dirty(
        "enseñamela",
        [{"role": "assistant", "content": "jajaja qué tal tu día"}],
    )


def test_owed_send_detects_stall():
    history = [
        {
            "role": "assistant",
            "content": "ay baby... ¿así tan fácil? pídemela bien y te la mando",
        }
    ]
    assert emma_owed_send(history)
    assert context_wants_max_dirty(
        "porfavor baby",
        history
        + [
            {
                "role": "assistant",
                "content": "la más guarra tocándome pensando en tu polla",
            }
        ],
    )


if __name__ == "__main__":
    test_como_de_guarra_is_max_dirty()
    test_emma_promise_plus_ensenamela()
    test_owed_send_detects_stall()
    print("ok")
