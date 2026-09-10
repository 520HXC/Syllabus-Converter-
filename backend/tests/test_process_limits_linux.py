"""Real Linux process checks, runnable directly without application dependencies."""

import json
import os
import subprocess
import sys
import time

import pytest

from app.process_limits import kill_worker_process_group

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux process isolation")


def test_address_space_limit_rejects_allocation():
    result = subprocess.run([sys.executable, "-c", """
from app.process_limits import isolate_worker_process
isolate_worker_process(128)
try:
    bytearray(256 * 1024 * 1024)
except MemoryError:
    print('memory allocation rejected')
else:
    raise AssertionError('memory ceiling did not apply')
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "memory allocation rejected" in result.stdout


def test_group_termination_stops_worker_and_external_child():
    worker = subprocess.Popen([sys.executable, "-c", """
import json, os, subprocess, sys, time
from app.process_limits import isolate_worker_process
isolate_worker_process(128)
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
print(json.dumps({'worker': os.getpid(), 'child': child.pid, 'group': os.getpgrp()}), flush=True)
time.sleep(60)
"""], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    group = None
    try:
        info = json.loads(worker.stdout.readline())
        group = info["group"]
        assert group == worker.pid
        assert os.getpgid(info["child"]) == group
        kill_worker_process_group(group)
        worker.wait(timeout=5)
        assert worker.returncode != 0
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with open(f"/proc/{info['child']}/stat") as status:
                    state = status.read().split()[2]
                if state == "Z":
                    break  # Reparented zombie has stopped and awaits init's reap.
            except FileNotFoundError:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("External OCR process survived its worker group")
    finally:
        if group:
            kill_worker_process_group(group)
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=5)


def test_cleanup_never_signals_its_own_group():
    kill_worker_process_group(os.getpgrp())
    kill_worker_process_group(os.getpid())
    kill_worker_process_group(None)


if __name__ == "__main__":
    assert sys.platform == "linux"
    test_address_space_limit_rejects_allocation()
    test_group_termination_stops_worker_and_external_child()
    test_cleanup_never_signals_its_own_group()
    print("3 real Linux process isolation checks passed")
