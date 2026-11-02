class QualfyError(Exception):
    """Base error for the framework."""


class ConfigError(QualfyError):
    pass


class SchemaError(QualfyError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(f"  {e}" for e in errors))


class ContractError(QualfyError):
    """A ticket does not satisfy the test-spec contract."""


class AdapterNotFound(QualfyError):
    pass


class SourceError(QualfyError):
    pass


class AgentError(QualfyError):
    pass


class SinkError(QualfyError):
    pass


class SessionError(QualfyError):
    pass
