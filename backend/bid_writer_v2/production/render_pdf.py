"""Refresh Writer indexes and export PDF with the application's LibreOffice.

Run with the Python provided by python3-uno, independently of the application's
Python version. A private named pipe and profile isolate simultaneous exports.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4


def stop_office(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=5)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def render(soffice: str, input_path: Path, output_path: Path) -> None:
    import uno

    def prop(name: str, value):
        item = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
        item.Name, item.Value = name, value
        return item

    input_path = input_path.resolve(strict=True)
    output_path = output_path.resolve()
    pipe_name = f"bidwriter_{uuid4().hex}"
    document = None
    desktop = None
    with tempfile.TemporaryDirectory(prefix="bid-writer-lo-") as temporary:
        profile = Path(temporary) / "profile"
        with (Path(temporary) / "office.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--nologo", "--nodefault",
                 "--norestore", "--nolockcheck", f"--accept=pipe,name={pipe_name};urp;StarOffice.ComponentContext"],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=(os.name == "posix"),
            )
            # Terminating this export's own office process also breaks a stuck UNO
            # call, so the helper cleans up before the parent's 180-second timeout.
            watchdog = threading.Timer(150, stop_office, args=(process,))
            watchdog.daemon = True
            watchdog.start()
            try:
                local = uno.getComponentContext()
                resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
                context = None
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("LibreOffice启动后提前退出")
                    try:
                        context = resolver.resolve(f"uno:pipe,name={pipe_name};urp;StarOffice.ComponentContext")
                        break
                    except Exception:
                        time.sleep(0.2)
                if context is None:
                    raise RuntimeError("LibreOffice目录更新连接超时")
                desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
                document = desktop.loadComponentFromURL(input_path.as_uri(), "_blank", 0, (
                    prop("Hidden", True), prop("ReadOnly", False),
                    prop("MacroExecutionMode", uno.getConstantByName("com.sun.star.document.MacroExecMode.NEVER_EXECUTE")),
                    prop("UpdateDocMode", uno.getConstantByName("com.sun.star.document.UpdateDocMode.NO_UPDATE")),
                ))
                if document is None:
                    raise RuntimeError("LibreOffice无法打开交付文档")
                indexes = document.getDocumentIndexes()
                if indexes.getCount() == 0:
                    raise RuntimeError("文档缺少可更新的原生目录")
                for _ in range(2):
                    document.refresh()
                    document.getTextFields().refresh()
                    for index in range(indexes.getCount()):
                        indexes.getByIndex(index).update()
                # Keep the DOCX stored beside the PDF consistent with the layout
                # used by the converter, including the real TOC page numbers.
                document.store()
                document.storeToURL(output_path.as_uri(), (
                    prop("FilterName", "writer_pdf_Export"), prop("Overwrite", True),
                ))
                if not output_path.is_file() or output_path.stat().st_size == 0:
                    raise RuntimeError("LibreOffice未生成PDF文件")
            finally:
                if document is not None:
                    try:
                        document.close(True)
                    except Exception:
                        pass
                if desktop is not None:
                    try:
                        desktop.terminate()
                    except Exception:
                        pass
                watchdog.cancel()
                stop_office(process)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--soffice", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        render(args.soffice, Path(args.input), Path(args.output))
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
