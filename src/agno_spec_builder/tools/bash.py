import asyncio
import os
import time

from agno.tools import Toolkit


class BashTools(Toolkit):
    def __init__(
        self,
        timeout: int = 120,
        cwd: str | None = None,
        env: dict | None = None,
        max_output: int = 100_000,
        **kwargs,
    ):
        self.timeout = timeout
        self.cwd = cwd
        self.env = {**os.environ, **(env or {})}
        self.max_output = max_output

        super().__init__(
            name="bash",
            tools=[self.run_shell_command],
            **kwargs,
        )

    async def run_shell_command(self, command: str, timeout: int | None = None) -> str:
        """Execute a shell command and return formatted stdout, stderr, and exit code.

        Runs commands via the system shell. Supports pipes, redirects, and quoting
        like a normal terminal.
        Args:
            command: Full bash command as one string
            timeout: Seconds before the command is killed. Defaults to the toolkit
                timeout (120s unless configured otherwise).

        Returns:
            Multi-section text: Exit Code, Duration, then STDOUT and/or STDERR.
            Non-zero exit codes are failures — read STDERR for the error message.
        """

        start = time.perf_counter()
        timeout = timeout or self.timeout

        try:
            # ["bash", "-c", ...] so pipes/redirects/quoting work as documented.
            process = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                command,
                cwd=self.cwd,
                env=self.env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)

            elapsed = time.perf_counter() - start

            stdout = stdout_bytes.decode(errors="replace").strip()
            stderr = stderr_bytes.decode(errors="replace").strip()

            if len(stdout) > self.max_output:
                stdout = stdout[: self.max_output] + "\n... (truncated)"

            if len(stderr) > self.max_output:
                stderr = stderr[: self.max_output] + "\n... (truncated)"

            parts = [
                f"Exit Code: {process.returncode}",
                f"Duration: {elapsed:.2f}s",
            ]

            if stdout:
                parts.append(f"STDOUT:\n{stdout}")

            if stderr:
                parts.append(f"STDERR:\n{stderr}")

            return "\n\n".join(parts)

        except TimeoutError:
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()
            return (
                f"Command timed out after {timeout} seconds.\n\n"
                f"Partial stdout:\n{stdout_bytes.decode(errors='replace').strip()}\n\n"
                f"Partial stderr:\n{stderr_bytes.decode(errors='replace').strip()}"
            )

        except Exception as e:
            from agno_spec_builder.utils import log

            log.exception("bash tool failed: %r", command)
            return f"{type(e).__name__}: {e}"
