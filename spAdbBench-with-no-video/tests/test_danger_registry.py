from adbtool.services.danger import DANGER_REGISTRY, RiskLevel, get_danger
from adbtool.ui.widgets.danger_dialog import DangerDialog


REQUIRED = {
    "reboot.system",
    "reboot.bootloader",
    "reboot.recovery",
    "reboot.edl",
    "reboot.fastbootd",
    "app.clear_data",
    "app.uninstall",
    "app.uninstall_keep_data",
    "app.batch_disable",
    "app.batch_disable_google",
    "display.set_size",
    "display.set_density",
    "settings.font_scale",
    "settings.animation",
    "settings.write_global",
    "settings.write_secure",
    "settings.write_system",
    "battery.simulate",
    "flash.unlock",
    "flash.lock",
    "flash.flash_partition",
    "flash.reboot_fastboot",
    "flash.reboot_recovery",
    "flash.reboot_edl",
    "files.push_system",
    "script.run",
    "snapshot.rollback",
    "device.tcpip",
    "device.disconnect",
}


def test_all_required_danger_keys_are_registered():
    assert REQUIRED <= set(DANGER_REGISTRY)


def test_every_danger_spec_has_command_and_impact():
    for spec in DANGER_REGISTRY.values():
        assert spec.command.strip()
        assert spec.impact.strip()
        assert spec.default_cancel is True
        assert spec.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_get_danger_can_override_command_and_count():
    spec = get_danger("app.uninstall", command="pm uninstall com.example", count=3)
    assert spec.command == "pm uninstall com.example"
    assert spec.count == 3


def test_dialog_cancel_is_default_and_shows_command(qtbot):
    dialog = DangerDialog(get_danger("app.uninstall", command="pm uninstall com.example"))
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.cancel_button.isDefault() is True
    assert dialog.confirm_button.isDefault() is False
    assert "pm uninstall com.example" in dialog.command_text.toPlainText()
    assert dialog.focusWidget() is dialog.cancel_button
