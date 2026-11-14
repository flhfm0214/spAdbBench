from adbtool.infrastructure.validation import quote_remote
from adbtool.services.settings_history import SettingsHistoryStore
from adbtool.services.snapshot_registry import (
    SNAPSHOT_FIELDS,
    build_dynamic_settings_fields,
    render_read,
    render_write,
)


def field(key: str):
    return next(item for item in SNAPSHOT_FIELDS if item.key == key)


def test_registry_contains_required_items():
    keys = {item.key for item in SNAPSHOT_FIELDS}

    assert {
        "display.size",
        "display.density",
        "system.font_scale",
        "global.window_animation_scale",
        "global.transition_animation_scale",
        "global.animator_duration_scale",
        "system.screen_off_timeout",
        "global.policy_control",
        "secure.icon_blacklist",
        "packages.disabled",
        "battery.simulation",
    } <= keys


def test_every_field_has_read_and_write_commands():
    for item in SNAPSHOT_FIELDS:
        assert item.read_command
        assert item.write_command
        assert item.key
        assert item.label
        assert item.group
        assert item.kind in {
            "raw",
            "int",
            "float",
            "bool",
            "package_list",
            "json",
        }


def test_registry_keys_are_unique():
    keys = [item.key for item in SNAPSHOT_FIELDS]
    assert len(keys) == len(set(keys))


def test_display_reset_and_set_write_commands():
    size = field("display.size")
    assert render_read(size) == "wm size"
    assert render_write(size, None) == "wm size reset"
    assert render_write(size, "1080x2400") == "wm size 1080x2400"

    density = field("display.density")
    assert render_write(density, None) == "wm density reset"
    assert render_write(density, 420) == "wm density 420"


def test_snapshot_field_marks_missing_values_unavailable():
    assert field("display.size").unavailable_when("") is True
    assert field("display.size").unavailable_when("1080x2400") is False
    assert field("system.font_scale").unavailable_when("null") is True
    assert field("system.font_scale").unavailable_when("1.0") is False
    assert field("global.policy_control").unavailable_when("null") is False


def test_dynamic_setting_roundtrip(tmp_path):
    store = SettingsHistoryStore(tmp_path / "history.json")
    store.record(
        "ABC",
        "secure",
        "icon_blacklist",
        "clock,alarm",
        "settings put secure icon_blacklist 'clock,alarm'",
    )

    fields = build_dynamic_settings_fields(store.entries("ABC"))
    dynamic = next(
        item for item in fields if item.key == "settings.secure.icon_blacklist"
    )

    assert dynamic.read_command == "settings get secure icon_blacklist"
    assert "settings put secure icon_blacklist" in dynamic.write_command
    assert render_read(dynamic) == "settings get secure icon_blacklist"
    assert (
        render_write(dynamic, "wifi,bluetooth")
        == "settings put secure icon_blacklist 'wifi,bluetooth'"
    )


def test_dynamic_fields_deduplicate_latest_history_entry(tmp_path):
    store = SettingsHistoryStore(tmp_path / "history.json")
    store.record("ABC", "system", "font_scale", "1.1", "settings put system font_scale 1.1")
    store.record("ABC", "system", "font_scale", "1.2", "settings put system font_scale 1.2")

    fields = build_dynamic_settings_fields(store.entries("ABC"))

    assert [item.key for item in fields] == ["settings.system.font_scale"]


def test_setting_write_values_are_shell_quoted():
    font = field("system.font_scale")
    value = "1.0'; reboot; #"

    command = render_write(font, value)

    assert command == f"settings put system font_scale {quote_remote(value)}"


def test_none_without_reset_command_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        render_write(field("system.font_scale"), None)
