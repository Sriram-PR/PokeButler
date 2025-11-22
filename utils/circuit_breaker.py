"""
Circuit Breaker Pattern Implementation for Async Functions.

Prevents cascade failures by detecting unhealthy services and stopping
requests until the service recovers.

States:
- CLOSED: Normal operation, requests pass through.
- OPEN: Service unhealthy, requests fail immediately.
- HALF_OPEN: Testing if service recovered, limited requests allowed.

Based on Michael Nygard's "Release It!" pattern.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("smogon_bot.circuit_breaker")


class CircuitState(Enum):
    """Enumeration of circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject all requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open and refusing requests."""

    pass


class CircuitBreaker:
    """
    Async Circuit Breaker implementation.

    Protects against cascade failures by monitoring API health and
    temporarily blocking requests when a service is unhealthy. It manages
    state transitions between CLOSED, OPEN, and HALF_OPEN based on failure
    counts and recovery timeouts.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
        expected_exceptions: tuple = (Exception,),
        name: Optional[str] = None,
    ):
        """
        Initialize the circuit breaker.

        Args:
            failure_threshold: Number of consecutive failures before opening the circuit.
            recovery_timeout: Seconds to wait in OPEN state before attempting recovery.
            success_threshold: Number of consecutive successes needed to close the
                circuit from HALF_OPEN state.
            expected_exceptions: Tuple of exception types that count as failures.
            name: Optional name for logging and monitoring purposes.
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.expected_exceptions = expected_exceptions
        self.name = name or "circuit_breaker"

        # State tracking
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        # Use monotonic time for reliable duration calculation (unaffected by system clock changes)
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

        logger.info(
            f"Circuit breaker '{self.name}' initialized",
            extra={
                "breaker_name": self.name,
                "failure_threshold": failure_threshold,
                "recovery_timeout": recovery_timeout,
            },
        )

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function with circuit breaker protection.

        This is the main entry point. It checks the circuit state before
        execution. If OPEN, it raises CircuitBreakerError immediately.
        If CLOSED or HALF_OPEN, it attempts execution and updates state
        based on success or failure.

        Args:
            func: The async function to execute.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            The result of the executed function.

        Raises:
            CircuitBreakerError: If the circuit is OPEN.
            Exception: The original exception raised by the function if it fails.
        """
        async with self._lock:
            # Check if we should attempt recovery
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    logger.info(
                        f"Circuit breaker '{self.name}' entering half-open state",
                        extra={
                            "breaker_name": self.name,
                            "previous_failures": self._failure_count,
                        },
                    )
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                else:
                    # Still open, reject immediately
                    # Calculate remaining time using monotonic time
                    time_since = time.monotonic() - self._last_failure_time
                    logger.debug(
                        f"Circuit breaker '{self.name}' is open, rejecting call",
                        extra={
                            "breaker_name": self.name,
                            "time_since_failure": time_since,
                        },
                    )
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is open. "
                        f"Service unavailable, try again later."
                    )

        # Execute the function
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result

        except self.expected_exceptions:
            await self._on_failure()
            raise

    def __call__(self, func: Callable) -> Callable:
        """
        Decorator support for the circuit breaker.

        Usage:
            @breaker
            async def api_call():
                ...

        Args:
            func: The async function to decorate.

        Returns:
            Wrapped async function.
        """

        async def wrapper(*args, **kwargs):
            return await self.call(func, *args, **kwargs)

        return wrapper

    async def _on_success(self):
        """
        Handle a successful function call.

        Resets failure counts and closes the circuit if recovery threshold
        is met while in HALF_OPEN state.
        """
        async with self._lock:
            self._failure_count = 0

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                logger.debug(
                    f"Circuit breaker '{self.name}' success in half-open state",
                    extra={
                        "breaker_name": self.name,
                        "success_count": self._success_count,
                        "threshold": self.success_threshold,
                    },
                )

                if self._success_count >= self.success_threshold:
                    logger.info(
                        f"Circuit breaker '{self.name}' closing after recovery",
                        extra={
                            "breaker_name": self.name,
                            "consecutive_successes": self._success_count,
                        },
                    )
                    self._state = CircuitState.CLOSED
                    self._success_count = 0

    async def _on_failure(self):
        """
        Handle a failed function call.

        Increments failure counts and opens the circuit if the threshold is
        exceeded. If in HALF_OPEN state, a single failure re-opens the circuit.
        """
        async with self._lock:
            self._failure_count += 1
            # Use monotonic time
            self._last_failure_time = time.monotonic()

            logger.warning(
                f"Circuit breaker '{self.name}' failure",
                extra={
                    "breaker_name": self.name,
                    "failure_count": self._failure_count,
                    "threshold": self.failure_threshold,
                    "state": self._state.value,
                },
            )

            if self._state == CircuitState.HALF_OPEN:
                # Failed during recovery, go back to open immediately
                logger.error(
                    f"Circuit breaker '{self.name}' failed during recovery, reopening",
                    extra={
                        "breaker_name": self.name,
                        "failure_count": self._failure_count,
                    },
                )
                self._state = CircuitState.OPEN
                self._success_count = 0

            elif self._failure_count >= self.failure_threshold:
                # Too many failures, open the circuit
                logger.error(
                    f"Circuit breaker '{self.name}' opening due to failures",
                    extra={
                        "breaker_name": self.name,
                        "failure_count": self._failure_count,
                        "threshold": self.failure_threshold,
                    },
                )
                self._state = CircuitState.OPEN

    def _should_attempt_reset(self) -> bool:
        """
        Check if enough time has passed to attempt a reset.

        Uses time.monotonic() ensures that system clock changes (e.g. NTP updates)
        do not affect the timeout calculation.

        Returns:
            True if recovery_timeout has elapsed, False otherwise.
        """
        if self._last_failure_time is None:
            return True

        return (time.monotonic() - self._last_failure_time) >= self.recovery_timeout

    def get_stats(self) -> dict:
        """
        Get current circuit breaker statistics.

        Returns:
            Dictionary containing state, counts, and configuration.
        """
        return {
            "breaker_name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure_time": self._last_failure_time,
        }

    async def reset(self):
        """
        Manually reset the circuit breaker to CLOSED state.

        Useful for administrative interventions or testing.
        """
        async with self._lock:
            logger.info(
                f"Circuit breaker '{self.name}' manually reset",
                extra={"breaker_name": self.name},
            )
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
