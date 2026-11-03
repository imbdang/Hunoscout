"""Map của app: struct node/edge, pattern → graph cụ thể, nhận diện màn, đi trên graph."""
from .element import Element, parse
from .graph import Action, Edge, Map, Node, Target
from .lexicon import Lexicon
from .locate import Ambiguous, locate, satisfied
from .navigate import Lost, Navigator
from .pattern import instantiate, load_docs
from .resolved import Resolved
