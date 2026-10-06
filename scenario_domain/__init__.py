# ============================================================
# PLANAPP / VIBEPLANNER AI
#
# SCENARIO DOMAIN CONTEXT
#
# __init__.py
#
# API pública da camada de Domain Context.
#
# Os consumidores devem importar desta API pública sempre que
# possível, evitando dependência da estrutura interna do
# pacote.
# ============================================================

from .models import (
    DECISION,
    GAP,
    IMPLEMENTED,
    PROPOSAL,
    KNOWLEDGE_CLASSIFICATIONS,
    DomainContext,
    DomainKnowledgeSection,
)

from .provider import (
    DomainContextProvider,
    NullDomainContextProvider,
)


__all__ = [
    # --------------------------------------------------------
    # MODELS
    # --------------------------------------------------------

    "DomainContext",
    "DomainKnowledgeSection",

    # --------------------------------------------------------
    # PROVIDERS
    # --------------------------------------------------------

    "DomainContextProvider",
    "NullDomainContextProvider",

    # --------------------------------------------------------
    # CLASSIFICATIONS
    # --------------------------------------------------------

    "IMPLEMENTED",
    "DECISION",
    "PROPOSAL",
    "GAP",
    "KNOWLEDGE_CLASSIFICATIONS",
]
