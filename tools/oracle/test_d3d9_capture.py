#!/usr/bin/env python3
"""Exercise actual subprocess boundaries without claiming Windows/GPU coverage."""

import ctypes
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("capture", Path(__file__).with_name("d3d9_capture.py"))
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


MATCHING_EVENT = r'''<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System><Provider Name="SideBySide"/><EventID>33</EventID><Level>2</Level>
    <TimeCreated SystemTime="2026-10-27T04:00:00.0054321Z"/>
    <EventRecordID>42</EventRecordID><Channel>Application</Channel><Computer>stand-in</Computer>
  </System>
  <EventData><Data>stand-in dependency resolution failure</Data>
    <Data>C:\isolated\MikuDanceStudio.exe</Data></EventData>
</Event>'''


class FakeWin32:
    """API stand-in; DialogWindows itself and ctypes buffers remain real."""

    def __init__(self, windows):
        self.windows = windows
        self.calls = []
        self.last_error = 999
        self.failures = {}
        self.kernel32 = SimpleNamespace(SetLastError=self.set_error, GetLastError=lambda: self.last_error)
        names = ("EnumWindows", "EnumChildWindows", "GetWindowThreadProcessId", "GetClassNameW",
                 "GetDlgCtrlID", "GetWindowTextW", "GetWindowLongW", "GetParent", "GetWindow",
                 "GetMenu", "IsWindowVisible", "IsWindowEnabled", "GetWindowRect", "SendMessageTimeoutW")
        self.user32 = SimpleNamespace(**{name: unittest.mock.Mock(side_effect=self.function(name)) for name in names})
        self.user32.EnumWindows.side_effect = lambda callback, parameter: self.function("EnumWindows")(None, callback, parameter)

    def set_error(self, value):
        self.last_error = value

    def function(self, name):
        def call(hwnd, *args):
            self.calls.append((name, hwnd, args))
            if (name, hwnd) in self.failures:
                self.last_error = self.failures[name, hwnd]
                if name == "SendMessageTimeoutW":
                    args[-1]._obj.value = 777  # Undefined output must never become a successful result.
                return 0
            if name in ("EnumWindows", "EnumChildWindows"):
                callback = args[0]
                for identifier, window in list(self.windows.items()):
                    if (name == "EnumWindows" and window.get("top_level", True) or
                        name == "EnumChildWindows" and not window.get("top_level", True) and
                        window.get("root", window.get("parent")) == hwnd):
                        if not callback(identifier, 0):
                            self.last_error = 123  # Must not overwrite the saved callback error.
                            return 0
                return 1 if name == "EnumWindows" else 0  # Child API return value is unused.
            if hwnd not in self.windows:
                self.last_error = 1400
                return 0
            window = self.windows[hwnd]
            if name == "GetWindowThreadProcessId":
                args[0]._obj.value = window.get("pid", 77)
                return window.get("tid", 88)
            if name == "GetClassNameW":
                args[0].value = window["class"]
                return len(window["class"])
            if name == "GetWindowTextW":
                args[0].value = window.get("text", "")
                return len(args[0].value)
            if name == "SendMessageTimeoutW":
                message, count, parameter, flags, timeout, result = args
                if message == 13:
                    text = window.get("text", "")
                    ctypes.memmove(parameter, ctypes.create_unicode_buffer(text), (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar))
                    result._obj.value = len(text)
                return 1
            if name == "GetWindowRect":
                rect = args[0]._obj
                rect.left, rect.top, rect.right, rect.bottom = window.get("rect", (0, 0, 640, 360))
                return 1
            key = {"GetDlgCtrlID": "id", "GetWindowLongW": "style", "GetParent": "parent",
                   "GetWindow": "owner", "GetMenu": "menu", "IsWindowVisible": "visible",
                   "IsWindowEnabled": "enabled"}[name]
            return window.get(key, 1 if key in ("visible", "enabled") else 0)
        return call

    def observer(self, test):
        test.enterContext(patch.object(ctypes, "WinDLL", return_value=self.user32, create=True))
        test.enterContext(patch.object(ctypes, "WINFUNCTYPE", side_effect=lambda *args: lambda function: function, create=True))
        test.enterContext(patch.object(ctypes, "set_last_error", side_effect=self.kernel32.SetLastError, create=True))
        test.enterContext(patch.object(ctypes, "get_last_error", side_effect=self.kernel32.GetLastError, create=True))
        windows = capture.DialogWindows()
        self.windows_api = windows
        return windows


def dialog_metadata():
    return {10: {"class": "#32770", "parent": 20, "owner": 20},
            11: {"class": "Static", "top_level": False, "parent": 10,
                 "text": "Cannot make DirectSound!!"},
            12: {"class": "Button", "top_level": False, "parent": 10, "id": 1}}


class DialogWin32Boundary(unittest.TestCase):
    def rejected(self, fake, windows=None):
        windows = windows or fake.observer(self)
        with self.assertRaisesRegex(ValueError, "^Unexpected dialog Static or IDOK metadata$") as raised:
            windows.snapshot(77)
        error = raised.exception
        self.assertFalse(hasattr(error, "api_error"))
        self.assertTrue(all(window["text"] is None for window in error.partial_windows))
        self.assertFalse(any(name == "SendMessageTimeoutW" and args[0] != 13
                             for name, _, args in fake.calls))
        return error

    def test_rejected_id2_text_is_supplemental_even_when_known(self):
        for body in ("Cannot make DirectSound!!", "Unknown warning"):
            with self.subTest(body=body):
                metadata = dialog_metadata()
                metadata[12]["id"] = 2
                metadata[10]["text"] = "Observed caption"
                metadata[11]["text"] = body
                metadata[20] = {"class": "Polygon Movie Maker", "visible": 0}
                metadata[30] = {"class": "IME", "visible": 0}
                fake = FakeWin32(metadata)
                error = self.rejected(fake)
                diagnostic = error.supplementary_diagnostics
                self.assertEqual(diagnostic["status"], "OBSERVED")
                self.assertEqual([query["text"] for query in diagnostic["queries"]], ["Observed caption", body])
                self.assertEqual(len(diagnostic["revalidations"]), 4)
                for validation in diagnostic["revalidations"]:
                    self.assertEqual(validation["status"], "MATCHED")
                    self.assertEqual([item["hwnd"] for item in validation["windows"]], [10, 11, 12])
                self.assertEqual([(name, hwnd) for name, hwnd, _ in fake.calls if name in ("GetWindowTextW", "SendMessageTimeoutW")],
                                 [("GetWindowTextW", 10), ("SendMessageTimeoutW", 11)])
                for query in diagnostic["queries"]:
                    context = query["context"]
                    self.assertEqual(context["last_error"], 0)
                    self.assertLessEqual(context["start_monotonic"], context["end_monotonic"])
                    self.assertIn("return", context)
                context = diagnostic["queries"][1]["context"]
                self.assertEqual((context["message"], context["flags"]), (13, 0x22))
                self.assertTrue(0 < context["timeout_ms"] <= 200)
                self.assertEqual(diagnostic["queries"][1]["message_result"], len(body))
                json.dumps(diagnostic)

    def test_rejected_secondary_api_errors_never_replace_metadata_error(self):
        for api, hwnd in (("SendMessageTimeoutW", 11), ("GetWindowTextW", 10)):
            for last_error in (0, 1460, 5, 1400):
                if api == "GetWindowTextW" and last_error == 0:
                    continue
                with self.subTest(api=api, last_error=last_error):
                    metadata = dialog_metadata()
                    metadata[12]["id"] = 2
                    fake = FakeWin32(metadata)
                    fake.failures[api, hwnd] = last_error
                    diagnostic = self.rejected(fake).supplementary_diagnostics
                    query = diagnostic["queries"][-1]
                    self.assertEqual(query["status"], "UNAVAILABLE")
                    self.assertNotIn("text", query)
                    self.assertNotIn("message_result", query)
                    self.assertEqual(query["api_error"]["last_error"], last_error)
                    self.assertEqual(query["api_error"]["return"], 0)
                    self.assertEqual(sum(name == api and handle == hwnd for name, handle, _ in fake.calls), 1)
                    self.assertEqual(diagnostic["status"], "PARTIAL" if api == "SendMessageTimeoutW" else "UNAVAILABLE")

    def test_rejected_metadata_changes_after_each_read_discard_its_text(self):
        mutations = ((10, "pid", 78), (10, "tid", 89), (10, "class", "Other"),
                     (10, "owner", 21), (10, "parent", 21), (10, "visible", 0),
                     (10, "enabled", 0), (11, "id", 4), (11, "style", 3),
                     (11, "parent", 20), (11, "visible", 0), (12, "id", 1),
                     (12, "enabled", 0), (12, "pid", 78), (11, "destroy", None))
        for trigger in ("GetWindowTextW", "SendMessageTimeoutW"):
            for hwnd, key, value in mutations:
                with self.subTest(trigger=trigger, hwnd=hwnd, key=key):
                    metadata = dialog_metadata()
                    metadata[12]["id"] = 2
                    fake = FakeWin32(metadata)
                    original = getattr(fake.user32, trigger).side_effect
                    def mutate(*args):
                        returned = original(*args)
                        if key == "destroy":
                            del metadata[hwnd]
                        else:
                            metadata[hwnd][key] = value
                        return returned
                    getattr(fake.user32, trigger).side_effect = mutate
                    diagnostic = self.rejected(fake).supplementary_diagnostics
                    self.assertNotEqual(diagnostic["status"], "OBSERVED")
                    self.assertNotIn("text", diagnostic["queries"][-1])
                    self.assertNotIn("message_result", diagnostic["queries"][-1])
                    self.assertNotEqual(diagnostic["revalidations"][-1]["status"], "MATCHED")
                    self.assertEqual(sum(name == trigger for name, _, _ in fake.calls), 1)

    def test_rejected_prevalidation_failure_prevents_text_queries(self):
        for label in ("changed", "destroyed", "api-error"):
            with self.subTest(label=label):
                metadata = dialog_metadata()
                metadata[12]["id"] = 2
                fake = FakeWin32(metadata)
                original = fake.user32.GetWindowThreadProcessId.side_effect
                counts = {}
                def change_before(hwnd, *args):
                    counts[hwnd] = counts.get(hwnd, 0) + 1
                    if hwnd == 10 and counts[hwnd] == 2:
                        if label == "changed":
                            metadata[10]["pid"] = 78
                        elif label == "destroyed":
                            del metadata[10]
                        else:
                            fake.failures["GetWindowThreadProcessId", 10] = 5
                    return original(hwnd, *args)
                fake.user32.GetWindowThreadProcessId.side_effect = change_before
                diagnostic = self.rejected(fake).supplementary_diagnostics
                self.assertEqual(diagnostic["status"], "UNAVAILABLE")
                self.assertEqual(diagnostic["queries"], [])
                self.assertFalse(any(name in ("GetWindowTextW", "SendMessageTimeoutW") for name, _, _ in fake.calls))

    def test_rejected_qualification_does_not_expand_text_scope(self):
        for label in ("unknown", "hidden", "disabled", "ambiguous", "unowned", "hidden-static",
                      "extra-static", "icon", "extra-button", "hidden-button", "disabled-button", "wrong-pid"):
            with self.subTest(label=label):
                metadata = dialog_metadata()
                metadata[12]["id"] = 2
                if label == "unknown":
                    metadata[90] = {"class": "Unknown"}
                elif label == "ambiguous":
                    metadata[90] = {"class": "#32770"}
                elif label == "hidden":
                    metadata[10]["visible"] = 0
                elif label == "disabled":
                    metadata[10]["enabled"] = 0
                elif label == "unowned":
                    metadata[10]["owner"] = 0
                elif label == "hidden-static":
                    metadata[11]["visible"] = 0
                elif label == "extra-static":
                    metadata[13] = dict(metadata[11])
                elif label == "icon":
                    metadata[11]["style"] = 3
                elif label == "extra-button":
                    metadata[13] = dict(metadata[12])
                elif label == "hidden-button":
                    metadata[12]["visible"] = 0
                elif label == "disabled-button":
                    metadata[12]["enabled"] = 0
                else:
                    metadata[12]["pid"] = 78
                fake = FakeWin32(metadata)
                with self.assertRaises(ValueError) as raised:
                    fake.observer(self).snapshot(77)
                self.assertFalse(hasattr(raised.exception, "supplementary_diagnostics"))
                self.assertFalse(any(name in ("GetWindowTextW", "SendMessageTimeoutW") for name, _, _ in fake.calls))

    def test_rejected_uses_shared_deadline_without_extra_query_or_retry(self):
        for phase in ("before", "after-caption", "body-timeout"):
            with self.subTest(phase=phase):
                metadata = dialog_metadata()
                metadata[12]["id"] = 2
                fake = FakeWin32(metadata)
                windows = fake.observer(self)
                windows.deadline = 20
                original = fake.user32.GetWindowTextW.side_effect
                def expire(*args):
                    returned = original(*args)
                    windows.deadline = 10.0005 if phase == "after-caption" else 10.025
                    return returned
                fake.user32.GetWindowTextW.side_effect = expire
                if phase == "before":
                    windows.deadline = 10.0005
                with patch.object(capture.time, "monotonic", return_value=10):
                    diagnostic = self.rejected(fake, windows).supplementary_diagnostics
                queries = [args for name, _, args in fake.calls if name == "SendMessageTimeoutW"]
                if phase == "body-timeout":
                    self.assertEqual(len(queries), 1)
                    self.assertTrue(0 < queries[0][4] <= 25)
                    self.assertEqual(windows.deadline, 10.025)
                else:
                    self.assertEqual(queries, [])
                    self.assertNotEqual(diagnostic["status"], "OBSERVED")
                    self.assertEqual(sum(name == "GetWindowTextW" for name, _, _ in fake.calls), 0 if phase == "before" else 1)

    def test_rejected_diagnostics_transfer_to_json_and_owned_cleanup(self):
        metadata = dialog_metadata()
        metadata[12]["id"] = 2
        fake = FakeWin32(metadata)
        windows = fake.observer(self)
        process = unittest.mock.Mock(pid=77, returncode=-9)
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "trusted.exe"
            executable.write_bytes(b"fixture")
            with patch.object(capture, "os", SimpleNamespace(name="nt")), patch.object(capture, "DialogWindows", return_value=windows), patch.object(capture.subprocess, "Popen", return_value=process):
                result = capture.observe_recoverable_dialog(executable, root / "input.pmm", root / "observation")
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["cause"], "Unexpected dialog Static or IDOK metadata")
            self.assertEqual(result["button_commands"], 0)
            self.assertNotIn("api_error", result)
            self.assertNotIn("dialog", result)
            self.assertNotIn("main_window", result)
            self.assertEqual(result["supplementary_diagnostics"]["status"], "OBSERVED")
            self.assertTrue(all(window["text"] is None for window in result["partial_windows"]))
            self.assertEqual(json.loads((root / "observation/observation.json").read_text()), result)
            process.kill.assert_called_once_with()
            process.wait.assert_called_once_with(timeout=10)

    def test_metadata_only_for_hidden_main_ime_buttons_and_irrelevant_children(self):
        fake = FakeWin32({20: {"class": "Polygon Movie Maker", "visible": 0},
                          30: {"class": "IME", "visible": 0},
                          21: {"class": "Button", "top_level": False, "parent": 20},
                          22: {"class": "Static", "top_level": False, "parent": 20}})
        windows = fake.observer(self)
        facts = windows.snapshot(77)
        self.assertEqual(len(facts), 4)
        self.assertTrue(all(window["text"] is None for window in facts))
        self.assertTrue(all(window["tid"] == 88 for window in facts))
        self.assertFalse(any(name in ("GetWindowTextW", "SendMessageTimeoutW", "GetMenu", "GetWindowRect") for name, _, _ in fake.calls))
        ctypes.WinDLL.assert_called_once_with("user32", use_last_error=True)

    def test_only_needed_direct_static_and_caption_are_queried_and_facts_stable(self):
        metadata = dialog_metadata()
        metadata[20] = {"class": "Polygon Movie Maker", "enabled": 0}
        metadata[13] = {"class": "Static", "top_level": False, "root": 10, "parent": 12}
        fake = FakeWin32(metadata)
        windows = fake.observer(self)
        facts = windows.snapshot(77)
        self.assertEqual(windows.snapshot(77), facts)
        self.assertEqual([(name, hwnd) for name, hwnd, _ in fake.calls if name in ("SendMessageTimeoutW", "GetWindowTextW")],
                         [("GetWindowTextW", 10), ("SendMessageTimeoutW", 11)] * 2)
        self.assertEqual(next(item for item in facts if item["hwnd"] == 11)["text"], "Cannot make DirectSound!!")
        self.assertIsNone(next(item for item in facts if item["hwnd"] == 12)["text"])
        self.assertEqual(facts[0]["parent"], 20)  # Popup owner is not a child relationship.
        for name, _, arguments in fake.calls:
            if name == "SendMessageTimeoutW":
                self.assertEqual(arguments[3], 0x22)
                self.assertTrue(0 < arguments[4] <= 200)

    def test_metadata_rejects_unknown_hidden_ambiguous_and_nontext_static_without_query(self):
        for label in ("unknown", "hidden", "ambiguous", "hidden-static", "extra-static", "icon", "extra-button", "wrong-pid"):
            with self.subTest(label=label):
                metadata = dialog_metadata()
                if label == "unknown":
                    metadata[90] = {"class": "Unknown"}
                elif label == "hidden":
                    metadata[10]["visible"] = 0
                elif label == "ambiguous":
                    metadata[90] = {"class": "#32770"}
                elif label == "hidden-static":
                    metadata[11]["visible"] = 0
                elif label == "extra-static":
                    metadata[13] = dict(metadata[11])
                elif label == "icon":
                    metadata[11]["style"] = 3
                elif label == "extra-button":
                    metadata[13] = dict(metadata[12])
                else:
                    metadata[12]["pid"] = 78
                fake = FakeWin32(metadata)
                with self.assertRaises(ValueError):
                    fake.observer(self).snapshot(77)
                self.assertFalse(any(name in ("GetWindowTextW", "SendMessageTimeoutW") for name, _, _ in fake.calls))

    def test_generic_timeout_and_other_errors_keep_original_context_and_partial_metadata(self):
        for api, hwnd in (("SendMessageTimeoutW", 11), ("GetWindowTextW", 10), ("GetClassNameW", 12)):
            for last_error in (0, 1460, 5, 1400):
                if api != "SendMessageTimeoutW" and last_error == 0:
                    continue  # Empty caption with error 0 is valid.
                with self.subTest(api=api, last_error=last_error):
                    fake = FakeWin32(dialog_metadata())
                    fake.failures[api, hwnd] = last_error
                    windows = fake.observer(self)
                    with self.assertRaises(OSError) as raised:
                        windows.snapshot(77)
                    error = raised.exception
                    context = error.api_error
                    self.assertEqual((context["api"], context["hwnd"], context["return"], context["last_error"]), (api, hwnd, 0, last_error))
                    self.assertEqual(context["window"]["pid"], 77)
                    self.assertEqual(len(error.partial_windows), 3)
                    self.assertLessEqual(context["start_monotonic"], context["end_monotonic"])
                    self.assertNotIn("message_result", context)
                    if api == "SendMessageTimeoutW":
                        self.assertEqual(context["message"], 13)
                        self.assertEqual(context["flags"], 0x22)
                        self.assertTrue(0 < context["timeout_ms"] <= 200)
                    json.dumps({"api_error": context, "partial_windows": error.partial_windows})

    def test_deadline_cap_enum_failure_and_main_readiness(self):
        fake = FakeWin32({number: {"class": "IME", "visible": 0} for number in range(1, 258)})
        windows = fake.observer(self)
        with self.assertRaises(ValueError) as raised:
            windows.snapshot(77)
        self.assertEqual(len(raised.exception.partial_windows), 256)
        windows.deadline = 0
        with self.assertRaises(ValueError) as raised:
            windows.snapshot(77)
        self.assertEqual(raised.exception.partial_windows, [])
        fake = FakeWin32({})
        fake.failures["EnumWindows", None] = 5
        windows = fake.observer(self)
        with self.assertRaises(OSError) as raised:
            windows.snapshot(77)
        self.assertEqual(raised.exception.api_error["api"], "EnumWindows")
        fake = FakeWin32({20: {"class": "Polygon Movie Maker", "menu": 1},
                          21: {"class": "Button", "parent": 20, "top_level": False}})
        windows = fake.observer(self)
        facts = windows.snapshot(77)
        self.assertEqual(facts[0]["rect"], [0, 0, 640, 360])
        self.assertTrue(facts[0]["menu"])
        self.assertFalse(any(name == "SendMessageTimeoutW" for name, _, _ in fake.calls))

    def test_callback_deadline_and_bounded_messages_do_not_retry(self):
        fake = FakeWin32({20: {"class": "Polygon Movie Maker", "visible": 0},
                          21: {"class": "Button", "parent": 20, "top_level": False}})
        windows = fake.observer(self)
        real_class = fake.user32.GetClassNameW.side_effect
        def expire_after_class(*args):
            returned = real_class(*args)
            windows.deadline = 0
            return returned
        fake.user32.GetClassNameW.side_effect = expire_after_class
        with self.assertRaises(ValueError) as raised:
            windows.snapshot(77)
        self.assertEqual(len(raised.exception.partial_windows), 1)
        self.assertEqual(raised.exception.partial_windows[0]["class"], "Polygon Movie Maker")
        fake = FakeWin32(dialog_metadata())
        windows = fake.observer(self)
        windows.snapshot(77)
        windows.deadline = 10.05
        fake.failures["SendMessageTimeoutW", 12] = 1460
        with patch.object(capture.time, "monotonic", return_value=10), self.assertRaises(OSError) as raised:
            windows.message(12, 0xF5)
        self.assertEqual(raised.exception.api_error["stage"], "button command")
        self.assertTrue(0 < raised.exception.api_error["timeout_ms"] <= 50)
        self.assertEqual(len(raised.exception.partial_windows), 3)
        clicks = [arguments for name, hwnd, arguments in fake.calls if name == "SendMessageTimeoutW" and hwnd == 12]
        self.assertEqual(len(clicks), 1)
        self.assertEqual(clicks[0][:4], (0xF5, 0, 0, 0x22))

    def test_api_failure_reaches_observation_json_and_owned_cleanup(self):
        fake = FakeWin32(dialog_metadata())
        fake.failures["SendMessageTimeoutW", 11] = 0
        windows = fake.observer(self)
        process = unittest.mock.Mock(pid=77, returncode=-9)
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "trusted.exe"
            executable.write_bytes(b"fixture")
            with patch.object(capture, "os", SimpleNamespace(name="nt")), patch.object(capture, "DialogWindows", return_value=windows), patch.object(capture.subprocess, "Popen", return_value=process):
                result = capture.observe_recoverable_dialog(executable, root / "input.pmm", root / "observation")
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["api_error"]["last_error"], 0)
            self.assertEqual(result["api_error"]["api"], "SendMessageTimeoutW")
            self.assertEqual(len(result["partial_windows"]), 3)
            self.assertEqual(result["button_commands"], 0)
            self.assertEqual(json.loads((root / "observation/observation.json").read_text()), result)
            process.kill.assert_called_once_with()
            process.wait.assert_called_once_with(timeout=10)


class CaptureBoundary(unittest.TestCase):
    def test_recoverable_dialog_exact_match_and_fail_closed(self):
        def window(hwnd, cls, text="", parent=0, identifier=0, **extra):
            return dict(hwnd=hwnd, pid=77, **{"class": cls}, text=text, parent=parent,
                        id=identifier, owner=0, visible=True, enabled=True, menu=False,
                        rect=[0, 0, 640, 360], **extra)

        dialog = window(10, "#32770")
        text = window(11, "Static", "Cannot make DirectSound!!", 10)
        button = window(12, "Button", "OK", 10, 1)
        prompt = [dialog, text, button]
        main = window(20, "Polygon Movie Maker", "MikuDanceStudio")
        main["menu"] = True
        continued = [main, window(21, "Button", "", 20)]
        cases = {"exact": (prompt, continued), "timeout": ([], []),
                 "no-dialog": (continued, continued), "repeated": (prompt, prompt),
                 "ambiguous": (prompt + [window(13, "#32770")], continued)}
        for label, index, field, value in (
            ("title", 0, "text", "unexpected"), ("hidden", 0, "visible", False),
            ("disabled", 0, "enabled", False), ("wrong-pid", 0, "pid", 78),
            ("text", 1, "text", "Cannot make DirectSound!! extra"),
            ("id", 2, "id", 2), ("button-disabled", 2, "enabled", False),
            ("button-hidden", 2, "visible", False), ("wrong-parent", 2, "parent", 99),
        ):
            changed = [dict(item) for item in prompt]
            changed[index][field] = value
            cases[label] = (changed, continued)
        unknown = window(50, "UnknownDialog")
        unknown["top_level"] = True
        cases["unknown-window"] = ([unknown], continued)
        cases["missing-button"] = (prompt[:2], continued)
        cases["extra-button"] = (prompt + [window(14, "Button", "Cancel", 10, 2)], continued)
        cases["missing-static"] = ([dialog, button], continued)
        for label, (first, later) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                executable = root / "trusted.exe"
                executable.write_bytes(b"trusted fixture")
                process = unittest.mock.Mock(pid=77, returncode=-9)
                process.poll.return_value = None
                windows = unittest.mock.Mock()
                windows.snapshot.side_effect = [first, first] + [later] * 50
                ticks = iter(index / 10 for index in range(1000))
                with patch.object(capture, "os", SimpleNamespace(name="nt")), patch.object(capture, "DialogWindows", return_value=windows), patch.object(capture.subprocess, "Popen", return_value=process) as launch, patch.object(capture.time, "monotonic", side_effect=lambda: next(ticks)), patch.object(capture.time, "sleep"):
                    result = capture.observe_recoverable_dialog(executable, root / "selfshadow.pmm", root / "observation", 8)
                self.assertEqual(result["status"], "OBSERVED" if label == "exact" else "FAIL")
                self.assertEqual(result["exe_sha256"], capture.digest(executable))
                self.assertEqual(result["pid"], 77)
                self.assertEqual(result["command"], [str(executable), str(root / "selfshadow.pmm")])
                self.assertEqual(launch.call_args.kwargs["cwd"], root / "observation")
                clicks = [call for call in windows.message.call_args_list if call.args[1] == 0xF5]
                self.assertEqual(len(clicks), 1 if label in ("exact", "repeated") else 0)
                if clicks:
                    self.assertEqual(clicks[0].args, (12, 0xF5))
                    self.assertEqual(result["button_command"], {"hwnd": 12, "message": "BM_CLICK", "message_id": 245, "status": "COMPLETED"})
                process.kill.assert_called_once_with()
                process.wait.assert_called_once_with(timeout=10)
                self.assertEqual(json.loads((root / "observation/observation.json").read_text()), result)
                self.assertTrue((root / "observation/stdout.txt").exists())
                self.assertTrue((root / "observation/stderr.txt").exists())

    def test_recoverable_dialog_launch_exit_revalidation_and_cleanup_failures(self):
        for label in ("launch", "exit", "enumeration", "cleanup", "changed"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                exe = root / "trusted.exe"
                exe.write_bytes(b"trusted fixture")
                process = unittest.mock.Mock(pid=77, returncode=7)
                process.poll.return_value = 7 if label == "exit" else None
                if label == "cleanup":
                    process.wait.side_effect = capture.subprocess.TimeoutExpired("owned", 10)
                windows = unittest.mock.Mock()
                windows.snapshot.side_effect = OSError("enumeration failed")
                if label == "changed":
                    prompt = [dict(hwnd=10, pid=77, **{"class": "#32770"}, text="", parent=0, visible=True, enabled=True),
                              dict(hwnd=11, pid=77, **{"class": "Static"}, text="Cannot make DirectSound!!", parent=10),
                              dict(hwnd=12, pid=77, **{"class": "Button"}, text="OK", parent=10, id=1, visible=True, enabled=True)]
                    windows.snapshot.side_effect = [prompt, []]
                with patch.object(capture, "os", SimpleNamespace(name="nt")), patch.object(capture, "DialogWindows", return_value=windows), patch.object(capture.subprocess, "Popen", side_effect=OSError("launch failed") if label == "launch" else None, return_value=process):
                    result = capture.observe_recoverable_dialog(exe, root / "selfshadow.pmm", root / "observation")
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["button_commands"], 0)
                windows.message.assert_not_called()
                self.assertEqual(bool(result["cleanup"].get("error")), label == "cleanup")
                self.assertEqual(result["pid"], None if label == "launch" else 77)
                if label != "launch":
                    process.wait.assert_called_once_with(timeout=10)
                with self.assertRaises(FileExistsError):
                    capture.observe_recoverable_dialog(exe, root / "selfshadow.pmm", root / "observation")

    def test_observation_failure_does_not_suppress_existing_capture_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out, build = (Path(tmp) / name for name in ("repo", "evidence", "build"))
            root.mkdir()
            build.mkdir()
            for name in capture.SOURCES + capture.ASSETS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("stand-in source")
            for name in ("MikuDanceStudio.exe", "d3d9_capability.exe"):
                (build / name).write_text("stand-in executable")
            real_run = capture.run_command
            attempts = []
            def stand_in(command, directory):
                attempts.append(directory.name)
                return real_run([sys.executable, "-c", "raise SystemExit(7)" if directory.name == "frames" else "print('stand-in')"], directory)
            with patch.object(capture, "run_command", side_effect=stand_in), patch.object(capture, "observe_recoverable_dialog", side_effect=OSError("observer failure")):
                self.assertEqual(capture.capture(root, build, out, observe_dialog=True), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(attempts, ["source-identity", "capability", "frames", "edge"])
            self.assertEqual([item["status"] for item in report["commands"]], ["PASS", "PASS", "FAIL", "PASS"])
            self.assertEqual(report["recoverable_dialog_observation"]["status"], "FAIL")
            self.assertEqual(report["closure"]["status"], "PASS")

    def test_actual_exit_timeout_and_partial_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, body, timeout, status, code in (
                ("success", "print('ok')", 10, "PASS", 0),
                ("nonzero", "import sys; print('partial', flush=True); print('cause', file=sys.stderr); sys.exit(7)", 10, "FAIL", 7),
                ("timeout", "import time; print('partial', flush=True); time.sleep(5)", 0.2, "TIMEOUT", None),
            ):
                with self.subTest(name=name):
                    result = capture.run_command([sys.executable, "-c", body], root / name, timeout)
                    self.assertEqual(result["status"], status)
                    if code is not None:
                        self.assertEqual(result["returncode"], code)
                    self.assertTrue((root / name / "stderr.txt").exists())
                    self.assertIn("ok" if name == "success" else "partial", (root / name / "stdout.txt").read_text())
                    self.assertEqual(json.loads((root / name / "command.json").read_text()), result)
            for timeout in (0, 91):
                with self.assertRaises(ValueError):
                    capture.run_command([sys.executable], root / "invalid", timeout)
            result = capture.run_command([root / "missing.exe"], root / "launch-error")
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("launch failed", result["cause"])

    def test_structured_activation_error_and_bounded_process_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            error = OSError(22, "stand-in activation failure")
            error.winerror = 14001
            with patch.object(capture.subprocess, "Popen", side_effect=error):
                result = capture.run_command(["unchanged.exe", "--original"], Path(tmp) / "startup")
            self.assertFalse(result["process_started"])
            self.assertEqual(result["startup_error"]["winerror"], 14001)
            self.assertEqual(result["startup_error"]["errno"], 22)
            self.assertIsNone(result["returncode"])
            self.assertEqual(result["command"], ["unchanged.exe", "--original"])
            self.assertEqual(result["timeout_seconds"], 90)
            process = unittest.mock.Mock()
            process.wait.side_effect = [capture.subprocess.TimeoutExpired("stand-in", 0.1),
                                        capture.subprocess.TimeoutExpired("stand-in cleanup", 10)]
            process.poll.return_value = None
            with patch.object(capture.subprocess, "Popen", return_value=process):
                result = capture.run_command(["stand-in"], Path(tmp) / "timeout", 0.1)
            self.assertEqual(result["status"], "TIMEOUT")
            self.assertIn("0.1-second bound", result["cause"])
            self.assertIn("cleanup_error", result)
            process.kill.assert_called_once_with()
            self.assertEqual(process.wait.call_args.kwargs, {"timeout": 10})

    def test_scoped_activation_events_with_standin_commands(self):
        original = {"command": [r"C:\isolated\MikuDanceStudio.exe", "--mds-frame-dump"],
                    "cwd": "original frames", "startup_error": {"winerror": 14001},
                    "started_utc": "2026-10-27T04:00:00+00:00",
                    "finished_utc": "2026-10-27T04:00:00.010000+00:00"}
        for outcome in ("events", "empty", "invalid", "failure", "timeout", "exception", "message-failure"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "diagnostic"
                calls = []
                real_run = capture.run_command

                def stand_in_tool(command, target, timeout):
                    calls.append([str(value) for value in command])
                    if target.name.startswith("events"):
                        if outcome == "exception":
                            raise OSError("stand-in diagnostic exception")
                        if outcome == "failure":
                            body = "raise SystemExit(9)"
                        elif outcome == "timeout":
                            return real_run([sys.executable, "-c", "import time; time.sleep(5)"], target, 0.1)
                        else:
                            xml = f"<Events>{MATCHING_EVENT}</Events>"
                            if outcome == "empty":
                                xml = "<Events/>"
                            elif outcome == "invalid":
                                xml = "invalid XML"
                            body = f"import sys; sys.stdout.buffer.write({xml.encode('utf-16')!r})"
                    elif target.name == "messages" and outcome == "message-failure":
                        body = "raise SystemExit(8)"
                    else:
                        body = "print('stand-in tool help or dependency resolution failure message')"
                    return real_run([sys.executable, "-c", body], target, timeout)

                with patch.object(capture, "run_command", side_effect=stand_in_tool), patch.dict(os.environ, {"SystemRoot": "stand-in Windows"}), patch.object(capture.time, "sleep"):
                    result = capture.activation_diagnostics(original, directory)
                self.assertEqual(result["status"], "COLLECTED" if outcome == "events" else "INCOMPLETE")
                self.assertEqual(result["original_startup_error"], {"winerror": 14001})
                self.assertFalse(result["retry"])
                self.assertEqual(json.loads((directory / "diagnostic.json").read_text()), result)
                for command in calls:
                    self.assertTrue(command[0].endswith("wevtutil.exe"))
                    self.assertNotIn("stoptrace", command)
                    if "Application" in command:
                        query = next(value for value in command if value.startswith("/q:"))
                        self.assertIn("Provider[@Name='SideBySide']", query)
                        self.assertIn("EventData[Data='C:\\isolated\\MikuDanceStudio.exe']", query)
                        self.assertIn("2026-10-27T04:00:02.010Z", query)
                        self.assertIn("/c:8", command)
                self.assertLessEqual(len(calls), 5)
                if outcome == "timeout":
                    self.assertEqual(result["commands"][-1]["status"], "TIMEOUT")

    def test_main_validates_returned_activation_event_records(self):
        valid = MATCHING_EVENT
        namespace = ' xmlns="http://schemas.microsoft.com/win/2004/08/events/event"'
        provider = '<Provider Name="SideBySide"/>'
        cases = {
            "matching": (f"<Events>{valid}</Events>", 1),
            "empty": ("<Events/>", 0),
            "syntax": ("<Events>", 0),
            "wrong-root": (f"<Other>{valid}</Other>", 0),
            "unrelated-child": ("<Events><NotAnEvent/></Events>", 0),
            "event-as-wrapper": (valid, 0),
            "missing-namespace": (f'<Events>{valid.replace(namespace, "")}</Events>', 0),
            "wrong-namespace": (f'<Events>{valid.replace("/events/event", "/events/other")}</Events>', 0),
            "wrong-provider": (f'<Events>{valid.replace("SideBySide", "Unrelated")}</Events>', 0),
            "wrong-path": (f'<Events>{valid.replace("MikuDanceStudio.exe", "other.exe")}</Events>', 0),
            "partial-path": (f'<Events>{valid.replace("MikuDanceStudio.exe</Data>", "MikuDanceStudio.exe.extra</Data>")}</Events>', 0),
            "missing-provider": (f'<Events>{valid.replace(provider, "")}</Events>', 0),
            "missing-time": (f'<Events>{valid.replace("TimeCreated", "OtherTime")}</Events>', 0),
            "missing-data": (f'<Events>{valid.replace("EventData", "UserData")}</Events>', 0),
        }
        for label, stamp in (
            ("before", "2026-10-27T03:59:59.9999999Z"),
            ("after", "2026-10-27T04:00:02.011Z"),
            ("after-submicrosecond", "2026-10-27T04:00:02.0100001Z"),
            ("malformed-time", "not a timestamp"),
            ("invalid-date", "2026-02-30T04:00:00Z"),
            ("naive-time", "2026-10-27T04:00:00"),
            ("non-utc", "2026-10-27T05:00:00+01:00"),
            ("non-schema-time", "2026-10-27 04:00:00Z"),
        ):
            cases[label] = (f'<Events>{valid.replace("2026-10-27T04:00:00.0054321Z", stamp)}</Events>', 0)
        for label, stamp in (("lower-bound", "2026-10-27T04:00:00Z"),
                             ("upper-bound", "2026-10-27T04:00:02.0100000Z")):
            cases[label] = (f'<Events>{valid.replace("2026-10-27T04:00:00.0054321Z", stamp)}</Events>', 1)
        cases["mixed"] = (f'<Events>{valid}<NotAnEvent/>{valid.replace("SideBySide", "Unrelated")}'
                          f'{valid.replace("2026-10-27T04:00:00.0054321Z", "invalid")}{valid}</Events>', 2)
        for label, (xml, count) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root, out, build = (Path(tmp) / name for name in ("repo", "evidence", "build"))
                root.mkdir()
                build.mkdir()
                for name in capture.SOURCES + capture.ASSETS:
                    source = root / name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text("stand-in source")
                for name in ("MikuDanceStudio.exe", "d3d9_capability.exe"):
                    (build / name).write_text("stand-in executable")
                real_run = capture.run_command
                calls = []

                def stand_in_process(command, target, timeout=capture.TIMEOUT):
                    calls.append([str(value) for value in command])
                    if target.name == "frames":
                        error = OSError(22, "original activation failure")
                        error.winerror = 14001
                        with patch.object(capture.subprocess, "Popen", side_effect=error):
                            result = real_run(command, target, timeout)
                        result.update(command=[r"C:\isolated\MikuDanceStudio.exe", "--mds-frame-dump"],
                                      started_utc="2026-10-27T04:00:00+00:00",
                                      finished_utc="2026-10-27T04:00:00.010000+00:00")
                        return result
                    body = f"import sys; sys.stdout.buffer.write({xml.encode('utf-16')!r})" if target.name.startswith("events-") else "print('stand-in help or message')"
                    return real_run([sys.executable, "-c", body], target, timeout)

                argv = ["d3d9_capture.py", "--root", str(root), "--build", str(build), "--out", str(out)]
                with patch.object(capture, "os", SimpleNamespace(name="nt", environ=os.environ)), patch.dict(os.environ, {"SystemRoot": "stand-in Windows"}), patch.object(capture, "run_command", side_effect=stand_in_process), patch.object(capture.time, "sleep"), patch.object(sys, "argv", argv):
                    self.assertEqual(capture.main(), 1)
                report = json.loads((out / "report.json").read_text())
                diagnostic = report["activation_diagnostics"][0]
                self.assertEqual(diagnostic["status"], "COLLECTED" if count else "INCOMPLETE")
                self.assertEqual(diagnostic.get("event_count", 0), count)
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(report["commands"][2]["status"], "FAIL")
                self.assertEqual(report["commands"][2]["startup_error"]["winerror"], 14001)
                self.assertIn("original activation failure", report["commands"][2]["cause"])
                self.assertEqual(report["commands"][3]["status"], "PASS")
                self.assertEqual(report["cause"], report["original_error"])
                self.assertEqual(report["closure"]["status"], "PASS")
                self.assertEqual(len(report["closure"]["checks"]), 2 * len(report["copies"]))
                self.assertEqual((out / "activation/frames/events-0/stdout.txt").read_bytes(), xml.encode("utf-16"))
                self.assertTrue((out / "activation/frames/help/command.json").exists())
                self.assertTrue((out / "activation/frames/query-help/stdout.txt").exists())
                self.assertEqual((out / "activation/frames/messages/stdout.txt").exists(), bool(count))
                self.assertLessEqual(sum("wevtutil.exe" in call[0] for call in calls), 5)

    def test_activation_diagnostic_failure_preserves_capture_and_closure(self):
        for winerror, diagnostic_failure in ((14001, False), (14001, True), (2, False), (None, False)):
            with self.subTest(winerror=winerror, diagnostic_failure=diagnostic_failure), tempfile.TemporaryDirectory() as tmp:
                root, out, build = (Path(tmp) / name for name in ("repo", "evidence", "build"))
                root.mkdir()
                build.mkdir()
                for name in capture.SOURCES + capture.ASSETS:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("stand-in source")
                for name in ("MikuDanceStudio.exe", "d3d9_capability.exe"):
                    (build / name).write_text("stand-in executable")
                real_run = capture.run_command

                def stand_in_process(command, directory):
                    if directory.name == "frames":
                        error = OSError(22, "first activation error")
                        error.winerror = winerror
                        with patch.object(capture.subprocess, "Popen", side_effect=error):
                            return real_run(command, directory)
                    return real_run([sys.executable, "-c", "print('stand-in')"], directory)

                diagnostic = {"status": "INCOMPLETE", "cause": "stand-in missing event", "retry": False}
                windows = SimpleNamespace(name="nt", environ=os.environ)
                with patch.object(capture, "os", windows), patch.object(capture, "run_command", side_effect=stand_in_process), patch.object(capture, "activation_diagnostics", side_effect=OSError("diagnostic failed") if diagnostic_failure else None, return_value=diagnostic) as diagnose:
                    self.assertEqual(capture.capture(root, build, out), 1)
                report = json.loads((out / "report.json").read_text())
                if winerror == 14001:
                    diagnose.assert_called_once()
                else:
                    diagnose.assert_not_called()
                self.assertEqual(len(report["commands"]), 4)
                self.assertEqual(report["commands"][2]["startup_error"]["winerror"], winerror)
                self.assertIn("first activation error", report["commands"][2]["cause"])
                self.assertEqual(report["commands"][3]["status"], "PASS")
                self.assertEqual(report["closure"]["status"], "PASS")
                self.assertEqual(len(report["closure"]["checks"]), 2 * len(report["copies"]))
                self.assertIn("Native command failed", report["original_error"])
                self.assertEqual(report["cause"], report["original_error"])
                if winerror == 14001:
                    self.assertEqual(report["activation_diagnostics"][0]["status"], "INCOMPLETE")
                else:
                    self.assertNotIn("activation_diagnostics", report)
                self.assertFalse((out / "frames" / "selfshadow-0.png").exists())

    def test_missing_asset_is_strict_failure_with_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp) / "repo", Path(tmp) / "evidence"
            root.mkdir()
            for name in capture.SOURCES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("source")
            self.assertEqual(capture.capture(root, root / "build", out), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("chain8.pmd", report["cause"])
            self.assertEqual(report["commands"], [])
            self.assertEqual(len(report["copies"]), len(capture.SOURCES) + 1)
            self.assertEqual(report["closure"]["tracked_copies"], len(capture.SOURCES) + 1)
            self.assertEqual(len(report["closure"]["checks"]), 2 * (len(capture.SOURCES) + 1))
            missing = report["closure"]["checks"][-2]
            self.assertEqual(missing["status"], "missing")
            self.assertIsNone(missing["initial_sha256"])
            self.assertIn("initial_error", missing)
            self.assertTrue(report["files"])

    def test_prepared_hash_drift_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp) / "repo", Path(tmp) / "evidence"
            root.mkdir()
            for name in capture.SOURCES + capture.ASSETS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("source")
            real_run = capture.run_command
            def stand_in_git(command, directory):
                return real_run([sys.executable, "-c", "print('fixture-revision')"], directory)
            with patch.object(capture, "run_command", side_effect=stand_in_git):
                self.assertEqual(capture.capture(root, root / "build", out, prepare=True), 0)
            original = out / "source" / capture.ASSETS[0]
            self.assertEqual(original.read_text(), "source")
            (root / capture.ASSETS[0]).write_text("changed")
            self.assertEqual(capture.capture(root, root / "build", out), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("Prepared source hash changed", report["cause"])
            self.assertFalse((out / "runtime").exists())
            self.assertEqual(original.read_text(), "source")

    def test_zero_exit_without_frames_is_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out, build = Path(tmp) / "repo", Path(tmp) / "evidence", Path(tmp) / "build"
            root.mkdir()
            build.mkdir()
            for name in capture.SOURCES + capture.ASSETS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("source")
            for name in ("MikuDanceStudio.exe", "d3d9_capability.exe"):
                (build / name).write_text("stand-in executable")
            real_run = capture.run_command
            def stand_in_process(command, directory):
                return real_run([sys.executable, "-c", "print('diagnostic_result=supported;')"], directory)
            with patch.object(capture, "run_command", side_effect=stand_in_process):
                self.assertEqual(capture.capture(root, build, out), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(len(report["commands"]), 4)
            self.assertTrue(all(command["status"] == "PASS" for command in report["commands"]))
            self.assertIn("selfshadow-0.png", report["cause"])
            self.assertTrue((out / "edge" / "stdout.txt").exists())
            with self.assertRaisesRegex(FileExistsError, "existing runtime"):
                capture.capture(root, build, out)

    def test_partial_staging_checks_known_files_after_setup_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp) / "repo", Path(tmp) / "evidence"
            root.mkdir()
            for name in capture.SOURCES + capture.ASSETS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("source")
            real_run = capture.run_command
            with patch.object(capture, "run_command", side_effect=lambda command, directory:
                              real_run([sys.executable, "-c", "print('fixture-revision')"], directory)):
                self.assertEqual(capture.capture(root, root / "missing-build", out), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertIn("MikuDanceStudio.exe", report["original_error"])
            self.assertIn(report["original_error"], report["cause"])
            self.assertEqual(len(report["closure"]["checks"]), 2 * len(report["copies"]))
            self.assertTrue(all(check["status"] == "unchanged" for check in report["closure"]["checks"][:-2]))
            self.assertTrue(all(check["status"] == "missing" for check in report["closure"]["checks"][-2:]))

    def test_final_closure_on_actual_process_failures_and_success(self):
        for role in ("source", "copy"):
            for failure in ("nonzero", "timeout", "outputs", "success"):
                for mutation in ("changed", "missing", "unreadable", "unchanged"):
                    with self.subTest(role=role, failure=failure, mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                        root, out, build = (Path(tmp).resolve() / name for name in ("repo", "evidence", "build"))
                        root.mkdir()
                        build.mkdir()
                        for name in capture.SOURCES + capture.ASSETS:
                            path = root / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text("source")
                        for name in ("MikuDanceStudio.exe", "d3d9_capability.exe"):
                            (build / name).write_text("stand-in executable")
                        target = root / capture.ASSETS[0] if role == "source" else out / "runtime" / Path(capture.ASSETS[0]).name
                        initial = capture.digest(root / capture.ASSETS[0])
                        real_run = capture.run_command

                        def stand_in_process(command, directory):
                            body = "from pathlib import Path; import struct, time; print('diagnostic_result=supported;', flush=True); "
                            if directory.name == "frames":
                                body += f"target = Path({str(target)!r}); "
                                if mutation == "changed":
                                    body += "target.write_text('changed'); "
                                elif mutation == "missing":
                                    body += "target.unlink(); "
                                elif mutation == "unreadable":
                                    body += "target.unlink(); target.mkdir(); "
                                if failure == "nonzero":
                                    body += "raise SystemExit(7)"
                                elif failure == "timeout":
                                    body += "time.sleep(5)"
                                elif failure == "success":
                                    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 640, 360) + b"\0" * 9 + b"\0\0\0\0IEND\xaeB`\x82"
                                    body += f"[Path('selfshadow-' + str(frame) + '.png').write_bytes({png!r}) for frame in (0, 30)]"
                            elif directory.name == "edge":
                                body += "Path('selfshadow.edge.txt').write_text('mds-edge-probe 1\\n0 shadow 2048 2048 1\\n30 shadow 2048 2048 1\\n')"
                            return real_run([sys.executable, "-c", body], directory,
                                            0.2 if failure == "timeout" and directory.name == "frames" else 10)

                        with patch.object(capture, "run_command", side_effect=stand_in_process):
                            self.assertEqual(capture.capture(root, build, out),
                                             0 if failure == "success" and mutation == "unchanged" else 1)
                        report = json.loads((out / "report.json").read_text())
                        self.assertEqual(report["status"], "PASS" if failure == "success" and mutation == "unchanged" else "FAIL")
                        self.assertEqual(report["closure"]["status"], "PASS" if mutation == "unchanged" else "FAIL")
                        checks = [check for check in report["closure"]["checks"]
                                  if check["path"] == str(target) and check["role"] == role]
                        self.assertTrue(checks)
                        for check in checks:
                            self.assertEqual(check["initial_sha256"], initial)
                            self.assertEqual(check["status"], mutation)
                            if mutation in ("changed", "unchanged"):
                                self.assertEqual(check["final_sha256"], capture.digest(target))
                            else:
                                self.assertIsNone(check["final_sha256"])
                                self.assertIn("error", check)
                        self.assertEqual(len(report["closure"]["checks"]), 2 * len(report["copies"]))
                        self.assertEqual(len(report["commands"]), 4)
                        if failure in ("nonzero", "timeout"):
                            self.assertIn("Native command failed", report["original_error"])
                            self.assertEqual(report["commands"][2]["status"], "TIMEOUT" if failure == "timeout" else "FAIL")
                        elif failure == "outputs":
                            self.assertIn("selfshadow-0.png", report["original_error"])
                        else:
                            self.assertNotIn("original_error", report)
                            self.assertTrue(all(command["status"] == "PASS" for command in report["commands"]))
                        if failure != "success":
                            self.assertIn(report["original_error"], report["cause"])
                        if mutation != "unchanged":
                            self.assertIn("closure failed", report["cause"])

    def test_copy_hash_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "asset", Path(tmp) / "stage" / "asset"
            source.write_bytes(b"fixture")
            manifest = []
            capture.copy_checked(source, target, manifest)
            self.assertEqual(capture.digest(source), capture.digest(target))
            self.assertEqual(manifest[0]["sha256"], capture.digest(source))
            with self.assertRaises(FileExistsError):
                capture.copy_checked(source, target, manifest)
            target.write_bytes(b"keep")
            self.assertEqual(source.read_bytes(), b"fixture")

    def test_output_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "frames").mkdir()
            (out / "edge").mkdir()
            with self.assertRaises(FileNotFoundError):
                capture.validate_outputs(out)
            png_header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 640, 360) + b"\0" * 9 + b"\0\0\0\0IEND\xaeB`\x82"
            for frame in (0, 30):
                (out / "frames" / f"selfshadow-{frame}.png").write_bytes(png_header)
            edge = out / "edge" / "selfshadow.edge.txt"
            edge.write_text("mds-edge-probe 1\n0 shadow 2048 2048 1\n")
            with self.assertRaisesRegex(ValueError, "frame 30"):
                capture.validate_outputs(out)
            edge.write_text(edge.read_text() + "30 shadow 2048 2048 1\n")
            capture.validate_outputs(out)
            (out / "frames" / "selfshadow-30.png").write_bytes(b"partial PNG")
            with self.assertRaisesRegex(ValueError, "invalid"):
                capture.validate_outputs(out)


if __name__ == "__main__":
    unittest.main()
