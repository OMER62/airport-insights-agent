class EtlError(Exception):
    """Identify an expected ETL failure - the runner logs it and returns a failure sentinel."""


class EtlInputError(EtlError):
    """Identify invalid input configuration - correct the inputs before retrying."""


class EtlOutputError(EtlError):
    """Identify an output configuration conflict - choose another path or permit replacement."""


class EtlValidationError(EtlError):
    """Identify data that violates task rules - publication stops until the data is corrected."""
