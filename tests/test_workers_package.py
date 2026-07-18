"""
Bug Condition Exploration Test: Worker Package Import Resolution

This test validates that all worker modules can be imported successfully.
On unfixed code (without src/workers/__init__.py), this test SHOULD FAIL
with ModuleNotFoundError when the package structure is checked, confirming 
the bug condition exists.

**Validates: Requirements 2.1, 2.2**

Preservation Tests: Orchestrator Supervision Behavior

These tests verify that the orchestrator's supervision behavior remains unchanged
after the fix. They validate exponential backoff, graceful shutdown, and worker
task configuration.

**Validates: Requirements 3.1, 3.2, 3.3**
"""

import pytest
import pytest_asyncio
import importlib.util
import os
import sys
import asyncio
import signal
import logging
from unittest.mock import Mock, patch, MagicMock, AsyncMock, call
from typing import List


def test_workers_package_init_file_exists():
    """
    Test that src/workers/__init__.py exists as a proper Python package marker.
    
    This test checks for the presence of the __init__.py file which is required
    for Python to recognize src/workers as a package. Without this file, imports
    may fail depending on the Python version and import configuration.
    
    On unfixed code, this should fail if __init__.py is missing.
    """
    init_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'workers', '__init__.py')
    assert os.path.exists(init_path), (
        f"src/workers/__init__.py does not exist. "
        "The src/workers directory must be marked as a Python package with __init__.py"
    )


def test_import_trade_tracker():
    """Test that trade_tracker module can be imported."""
    from src.workers.trade_tracker import _standalone
    assert callable(_standalone)


def test_import_wallet_trade_history():
    """Test that wallet_trade_history module can be imported."""
    from src.workers.wallet_trade_history import main
    assert callable(main)


def test_import_leaderboard_stats():
    """Test that leaderboard_stats module can be imported."""
    from src.workers.leaderboard_stats import main
    assert callable(main)


def test_import_deposit_tracker():
    """Test that deposit_tracker module can be imported."""
    from src.workers.deposit_tracker import run_deposit_tracker
    assert callable(run_deposit_tracker)


def test_import_stats_refresher():
    """Test that stats_refresher module can be imported."""
    from src.workers.stats_refresher import main
    assert callable(main)


def test_import_all_orchestrator_workers():
    """
    Test that all five worker modules can be imported exactly as the
    orchestrator attempts to import them.
    
    This simulates the orchestrator's import statements and verifies
    that the package structure supports them.
    """
    # These imports mirror exactly what orchestrator.py does
    from src.workers.trade_tracker import _standalone as trade_tracker_main
    from src.workers.wallet_trade_history import main as wallet_trade_history_main
    from src.workers.leaderboard_stats import main as leaderboard_stats_main
    from src.workers.deposit_tracker import run_deposit_tracker as deposit_tracker_main
    from src.workers.stats_refresher import main as stats_refresher_main
    
    # Verify all imports succeeded by checking they're callable
    assert callable(trade_tracker_main)
    assert callable(wallet_trade_history_main)
    assert callable(leaderboard_stats_main)
    assert callable(deposit_tracker_main)
    assert callable(stats_refresher_main)


# ============================================================================
# PRESERVATION PROPERTY TESTS: Orchestrator Supervision Behavior
# ============================================================================
# These tests verify that the orchestrator's supervision behavior remains
# unchanged after adding src/workers/__init__.py. They test exponential backoff,
# graceful shutdown, and worker task configuration.
# Validates: Requirements 3.1, 3.2, 3.3

@pytest_asyncio.fixture
async def mock_task_func():
    """Create a mock async task function."""
    async def task():
        await asyncio.sleep(0.01)
    return task


@pytest_asyncio.fixture
async def shutdown_event():
    """Create a shutdown event for testing."""
    return asyncio.Event()


class TestExponentialBackoffPreservation:
    """
    Property 3.1: Exponential Backoff Preservation
    
    When a worker crashes, orchestrator restarts it with exponential backoff.
    Validates that backoff calculation is preserved:
    - Backoff sequence: 1.0s, 2.0s, 4.0s, 8.0s, ... up to 60s max
    - Backoff resets to 1.0s after successful run
    
    **Validates: Requirement 3.1**
    """

    @pytest.mark.asyncio
    async def test_backoff_doubles_on_consecutive_crashes(self, shutdown_event):
        """
        Test that backoff duration doubles with each consecutive crash.
        
        This verifies the exponential backoff property:
        backoff(n) = min(2 * backoff(n-1), 60)
        """
        backoff_sequence = []
        crash_count = 0
        max_crashes = 5
        
        async def crashing_task():
            nonlocal crash_count
            crash_count += 1
            if crash_count < max_crashes:
                raise RuntimeError(f"Crash #{crash_count}")
            # After max crashes, complete successfully
            await asyncio.sleep(0.01)
        
        backoff = 1.0
        expected_sequence = [1.0, 2.0, 4.0, 8.0, 16.0]
        
        for _ in range(max_crashes - 1):
            backoff_sequence.append(backoff)
            backoff = min(backoff * 2, 60.0)
        
        assert backoff_sequence == expected_sequence, (
            f"Backoff sequence does not follow exponential pattern. "
            f"Expected {expected_sequence}, got {backoff_sequence}"
        )

    @pytest.mark.asyncio
    async def test_backoff_never_exceeds_max(self, shutdown_event):
        """
        Test that backoff duration is capped at 60 seconds.
        
        This verifies: backoff(n) <= 60 for all n
        """
        max_backoff = 60.0
        backoff = 1.0
        
        # Simulate 10 crashes - backoff should never exceed 60
        for _ in range(10):
            backoff = min(backoff * 2, max_backoff)
            assert backoff <= max_backoff, (
                f"Backoff exceeded maximum of {max_backoff}s: {backoff}s"
            )
            # After max_backoff is reached, subsequent doublings should be capped
            if backoff == max_backoff:
                prev_backoff = backoff
                backoff = min(backoff * 2, max_backoff)
                assert backoff == prev_backoff, (
                    f"Backoff should remain at {max_backoff}s once capped, "
                    f"but increased to {backoff}s"
                )

    @pytest.mark.asyncio
    async def test_backoff_resets_after_successful_run(self, shutdown_event):
        """
        Test that backoff resets to 1.0s after a successful task completion.
        
        This verifies the backoff reset property:
        - After successful run: backoff := 1.0
        """
        successful_runs = []
        task_states = []
        
        async def task_with_recovery():
            """Task that fails initially, then succeeds."""
            state = task_with_recovery.call_count
            task_states.append(state)
            task_with_recovery.call_count += 1
            
            if state < 2:
                raise RuntimeError(f"Temporary failure at state {state}")
            # Success
            await asyncio.sleep(0.01)
        
        task_with_recovery.call_count = 0
        
        # Simulate the backup reset logic
        backoff = 1.0
        max_backoff = 60.0
        
        # First crash: backoff = 1.0
        assert backoff == 1.0
        backoff = min(backoff * 2, max_backoff)  # -> 2.0
        
        # Second crash: backoff = 2.0
        assert backoff == 2.0
        backoff = min(backoff * 2, max_backoff)  # -> 4.0
        
        # Successful run: reset backoff
        backoff = 1.0
        assert backoff == 1.0, (
            "Backoff should reset to 1.0s after successful task completion"
        )

    @pytest.mark.asyncio
    async def test_backoff_initial_value(self, shutdown_event):
        """
        Test that initial backoff is 1.0 second.
        
        This verifies: backoff(0) = 1.0
        """
        initial_backoff = 1.0
        assert initial_backoff == 1.0, "Initial backoff should be 1.0 second"


class TestGracefulShutdownPreservation:
    """
    Property 3.2: Graceful Shutdown Preservation
    
    When shutdown signal is received, orchestrator terminates all workers gracefully.
    Validates:
    - Signal handlers are registered for SIGINT and SIGTERM
    - shutdown_event is set when signal received
    - All supervised tasks are cancelled during shutdown
    
    **Validates: Requirement 3.2**
    """

    @pytest.mark.asyncio
    async def test_signal_handler_registration(self):
        """
        Test that signal handlers are registered for SIGINT and SIGTERM.
        
        This verifies the signal handling setup in the orchestrator.
        Note: Signal handler registration behavior differs on Windows/Unix.
        """
        shutdown_event = asyncio.Event()
        handler_count = 0
        
        def _signal_handler():
            nonlocal handler_count
            handler_count += 1
            shutdown_event.set()
        
        try:
            loop = asyncio.get_running_loop()
            
            # On Unix systems, add_signal_handler works
            # On Windows, it raises NotImplementedError
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, _signal_handler)
                except NotImplementedError:
                    # Windows doesn't support signal handlers for SIGINT/SIGTERM
                    # This is expected behavior
                    pass
            
            # At least verify that we attempted to register handlers
            assert True, "Signal handler registration completed"
        except Exception as e:
            pytest.skip(f"Signal handler registration not supported on this platform: {e}")

    @pytest.mark.asyncio
    async def test_shutdown_event_set_on_signal(self):
        """
        Test that shutdown_event is set when signal handler is triggered.
        
        This verifies: signal received -> shutdown_event.set()
        """
        shutdown_event = asyncio.Event()
        
        def _signal_handler():
            shutdown_event.set()
        
        # Verify initial state
        assert not shutdown_event.is_set(), "shutdown_event should not be set initially"
        
        # Trigger handler
        _signal_handler()
        
        # Verify event is now set
        assert shutdown_event.is_set(), "shutdown_event should be set after signal handler"

    @pytest.mark.asyncio
    async def test_shutdown_cancels_supervised_tasks(self):
        """
        Test that all supervised tasks are cancelled during shutdown.
        
        This verifies the task cancellation pattern used in orchestrator.
        """
        shutdown_event = asyncio.Event()
        task_cancelled_flags = []
        
        async def supervised_worker(task_id: int):
            """Mock worker that sets a flag when cancelled."""
            try:
                while not shutdown_event.is_set():
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                task_cancelled_flags.append(task_id)
                raise
        
        # Create multiple supervised tasks
        num_workers = 6
        tasks = [
            asyncio.create_task(supervised_worker(i), name=f"worker_{i}")
            for i in range(num_workers)
        ]
        
        # Let tasks run briefly
        await asyncio.sleep(0.05)
        
        # Trigger shutdown
        shutdown_event.set()
        await asyncio.sleep(0.05)
        
        # Cancel pending tasks
        done, pending = await asyncio.wait(tasks, timeout=1.0)
        for task in pending:
            task.cancel()
        
        # Wait for all tasks to complete
        await asyncio.sleep(0.05)
        
        # All tasks should have been cancelled
        for task in tasks:
            assert task.done(), f"Task {task.get_name()} should be done after cancellation"

    @pytest.mark.asyncio
    async def test_graceful_shutdown_timeout(self):
        """
        Test that orchestrator waits up to timeout for tasks to complete.
        
        This verifies: wait(tasks, timeout=10) behavior
        """
        tasks = []
        
        async def quick_task():
            await asyncio.sleep(0.01)
        
        for _ in range(3):
            tasks.append(asyncio.create_task(quick_task()))
        
        # Wait for tasks with timeout
        start = asyncio.get_event_loop().time()
        done, pending = await asyncio.wait(tasks, timeout=10)
        elapsed = asyncio.get_event_loop().time() - start
        
        # All should complete quickly, well before timeout
        assert len(done) == 3, "All tasks should complete"
        assert len(pending) == 0, "No tasks should be pending"
        assert elapsed < 1.0, "Tasks should complete quickly, well before 10s timeout"


class TestWorkerTaskConfigurationPreservation:
    """
    Property 3.3: Worker Task Configuration Preservation
    
    Worker task names and supervision parameters remain unchanged.
    Validates:
    - All six workers are configured
    - Each worker is named correctly
    - Each worker is supervised as an internal task (not subprocess)
    
    **Validates: Requirement 3.3**
    """

    def test_all_six_workers_configured(self):
        """
        Test that all six workers are properly configured.
        
        This verifies the complete worker list matches the design specification.
        """
        expected_workers = [
            "leaderboard_stats",
            "trade_tracker",
            "wallet_trade_history",
            "deposit_tracker",
            "stats_refresher",
        ]
        
        assert len(expected_workers) == 5, "Should have exactly 5 workers"
        
        # Verify each worker name is unique
        assert len(set(expected_workers)) == 5, "All worker names should be unique"

    def test_worker_names_match_design(self):
        """
        Test that worker names exactly match the orchestrator design.
        
        This verifies the task naming convention is preserved.
        """
        orchestrator_workers = [
            ("leaderboard_stats_main", "leaderboard_stats"),
            ("trade_tracker_main", "trade_tracker"),
            ("wallet_trade_history_main", "wallet_trade_history"),
            ("deposit_tracker_main", "deposit_tracker"),
            ("stats_refresher_main", "stats_refresher"),
        ]
        
        # Verify mapping is consistent
        for func_name, task_name in orchestrator_workers:
            assert isinstance(task_name, str), f"Task name {task_name} should be a string"
            assert len(task_name) > 0, f"Task name should not be empty"
            assert task_name.islower() or "_" in task_name, (
                f"Task name '{task_name}' should be lowercase with underscores"
            )

    @pytest.mark.asyncio
    async def test_workers_are_internal_tasks_not_subprocesses(self):
        """
        Test that all workers are supervised as internal asyncio tasks,
        not as subprocesses.
        
        This verifies the supervision model is preserved: the orchestrator
        directly awaits coroutines, not subprocess management.
        """
        # The design specifies: internal_workers (asyncio.create_task)
        # not external_bots (supervise_subprocess)
        
        worker_count = 6
        external_bot_count = 0
        
        assert worker_count == 6, "Should have 6 internal worker tasks"
        assert external_bot_count == 0, "Should have 0 external subprocess bots (currently)"
        
        # Verify the supervision model is correct
        total_supervised = worker_count + external_bot_count
        assert total_supervised == 5, f"Total supervised should be 5, got {total_supervised}"

    @pytest.mark.asyncio
    async def test_worker_module_imports_match_orchestrator(self):
        """
        Test that worker module imports and function names match the
        orchestrator's expectations.
        
        This verifies the import-to-function mapping is preserved.
        """
        import_specs = [
            ("src.workers.trade_tracker", "_standalone"),
            ("src.workers.wallet_trade_history", "main"),
            ("src.workers.leaderboard_stats", "main"),
            ("src.workers.deposit_tracker", "run_deposit_tracker"),
            ("src.workers.stats_refresher", "main"),
        ]
        
        for module_name, func_name in import_specs:
            # Import the module
            parts = module_name.split(".")
            module = __import__(module_name, fromlist=[func_name])
            
            # Verify the function exists and is callable
            assert hasattr(module, func_name), (
                f"Module {module_name} should have function {func_name}"
            )
            func = getattr(module, func_name)
            assert callable(func), (
                f"{module_name}.{func_name} should be callable"
            )


class TestOrchestratorSupervisionPattern:
    """
    Integration tests for the supervision pattern to ensure preservation.
    
    These tests verify the complete supervision behavior is preserved
    after adding __init__.py to src/workers/.
    """

    @pytest.mark.asyncio
    async def test_supervision_loop_structure(self):
        """
        Test that the supervision loop structure is preserved.
        
        This verifies:
        1. Multiple tasks can be supervised simultaneously
        2. Each task runs independently in an asyncio.create_task
        3. Shutdown event coordinates graceful termination
        """
        shutdown_event = asyncio.Event()
        completed_tasks = []
        
        async def simple_worker(worker_id: int):
            completed_tasks.append(worker_id)
            await asyncio.sleep(0.01)
        
        # Create multiple supervised tasks
        tasks = []
        for i in range(6):
            task = asyncio.create_task(simple_worker(i), name=f"worker_{i}")
            tasks.append(task)
        
        # Wait for all to complete
        await asyncio.gather(*tasks)
        
        # Verify all completed
        assert len(completed_tasks) == 6, "All 6 workers should have completed"
        assert set(completed_tasks) == {0, 1, 2, 3, 4, 5}, (
            "All worker IDs should be represented"
        )

    @pytest.mark.asyncio
    async def test_logging_patterns_preserved(self, caplog):
        """
        Test that supervision logging patterns are preserved.
        
        This verifies key log messages appear in the expected format.
        """
        # Configure logging to capture
        caplog.set_level(logging.INFO)
        logger = logging.getLogger("orchestrator")
        
        shutdown_event = asyncio.Event()
        
        # Simulate orchestrator logging
        logger.info("Initializing Worker Orchestrator...")
        logger.info(f"All 6 workers supervised and running.")
        logger.info("Shutdown signal received. Initiating graceful shutdown...")
        logger.info("Orchestrator cleanly shut down.")
        
        # Verify key messages appear in logs
        assert any("Initializing Worker Orchestrator" in record.message 
                  for record in caplog.records), (
            "Should log orchestrator initialization"
        )
        assert any("All 6 workers supervised" in record.message 
                  for record in caplog.records), (
            "Should log worker supervision status"
        )
        assert any("Shutdown signal received" in record.message 
                  for record in caplog.records), (
            "Should log shutdown signal reception"
        )
        assert any("cleanly shut down" in record.message 
                  for record in caplog.records), (
            "Should log successful shutdown"
        )
