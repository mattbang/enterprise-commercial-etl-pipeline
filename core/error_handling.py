import logging
import collections
from typing import List, Dict, Optional

class PipelineErrorHandler(logging.Handler):
    """
    A custom logging handler that buffers log records of level WARNING and above.
    This allows the orchestrator to include a summary of issues in the final email report.
    """
    def __init__(self):
        super().__init__()
        self.warnings: List[logging.LogRecord] = []
        self.errors: List[logging.LogRecord] = []
        # Store context if needed, but LogRecord has most info
        
    def emit(self, record: logging.LogRecord):
        """Buffer the record if it matches criteria."""
        if record.levelno == logging.WARNING:
            self.warnings.append(record)
        elif record.levelno >= logging.ERROR:
            self.errors.append(record)

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def get_summary_text(self) -> str:
        """Return a formatted string summary of issues for email body."""
        lines = []
        
        if self.errors:
            lines.append(f"\n❌ ERRORS ({len(self.errors)}):")
            for r in self.errors:
                lines.append(f"  - [{r.name}] {r.getMessage()}")
        
        if self.warnings:
            lines.append(f"\n⚠️ WARNINGS ({len(self.warnings)}):")
            # Limit warnings if too many
            limit = 20
            for r in self.warnings[:limit]:
                lines.append(f"  - [{r.name}] {r.getMessage()}")
            
            if len(self.warnings) > limit:
                lines.append(f"  ... and {len(self.warnings) - limit} more warnings.")
                
        return "\n".join(lines) if lines else "No warnings or errors recorded."

    def get_last_error_detail(self) -> str:
        """Return the formatted traceback of the most recent error, if available."""
        if not self.errors:
            return "No errors recorded."
        last = self.errors[-1]
        if last.exc_info and last.exc_info[0] is not None:
            import traceback
            return "".join(traceback.format_exception(*last.exc_info))
        return f"[{last.name}] {last.getMessage()}"
