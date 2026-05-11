# ---------------------------------------------------------------------------
# Israa's DocumentAnalyzer class lives here.
# The implementation below is a MOCK — replace with the real class when ready.
#
# Interface contract (do NOT change method names or return types):
#   __init__(text: str)
#   .summary()    -> str
#   .key_points() -> list[str]
#   .entities()   -> dict  {"people": [...], "organizations": [...], "locations": [...]}
# ---------------------------------------------------------------------------


class DocumentAnalyzer:
    """Analyses pre-extracted text from a document.

    TODO: Replace the mock implementations below with Israa's real logic.
    The public interface (method names + return types) must stay the same
    so that the /api/analyze endpoint requires no changes after the swap.
    """

    def __init__(self, text: str) -> None:
        self._text = text

    def summary(self) -> str:
        """Return a short summary of the document.

        TODO: replace with Israa's real implementation.
        """
        # MOCK — returns a placeholder until Israa's module is ready
        return "Summary not yet available (mock response)."

    def key_points(self) -> list[str]:
        """Return a list of key points extracted from the document.

        TODO: replace with Israa's real implementation.
        """
        # MOCK — returns placeholder items until Israa's module is ready
        return [
            "Key point 1 (mock response).",
            "Key point 2 (mock response).",
            "Key point 3 (mock response).",
        ]

    def entities(self) -> dict:
        """Return named entities found in the document.

        TODO: replace with Israa's real implementation.
        Returns a dict with keys: 'people', 'organizations', 'locations'.
        """
        # MOCK — returns empty entity lists until Israa's module is ready
        return {
            "people": [],
            "organizations": [],
            "locations": [],
        }
