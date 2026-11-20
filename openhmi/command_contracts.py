"""Command history query contract shared by service and HTTP registration."""
from typing import Literal

CommandHistoryState = Literal['', 'unresolved', 'prepared', 'staging', 'requested', 'accepted',
                              'uncertain', 'completed', 'failed', 'interrupted']
