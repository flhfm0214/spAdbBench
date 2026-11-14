from adbtool.infrastructure.parsers import (
    parse_battery,
    parse_devices,
    parse_packages,
    parse_props,
    parse_wm_density,
    parse_wm_size,
)


def test_parse_devices_reads_state_model_and_transport():
    text = (
        "List of devices attached\n"
        "ABC123\tdevice product:panther model:Pixel_7 device:panther transport_id:1\n"
        "XYZ\tunauthorized usb:1-1 transport_id:2\n"
        "OFF\t offline transport_id:3\n"
    )

    devices = parse_devices(text)

    assert [d.serial for d in devices] == ["ABC123", "XYZ", "OFF"]
    assert devices[0].state == "device"
    assert devices[0].model == "Pixel 7"
    assert devices[0].display_name == "Pixel 7"
    assert devices[0].connected is True
    assert devices[1].state == "unauthorized"
    assert devices[2].state == "offline"


def test_parse_packages():
    assert parse_packages("package:com.a\npackage:com.b\n") == ["com.a", "com.b"]


def test_parse_wm_size_prefers_override():
    text = "Physical size: 1080x2400\nOverride size: 720x1600\n"
    effective, physical = parse_wm_size(text)
    assert effective == "720x1600"
    assert physical == "1080x2400"


def test_parse_wm_size_without_override():
    effective, physical = parse_wm_size("Physical size: 1080x2400\n")
    assert effective == "1080x2400"
    assert physical == "1080x2400"


def test_parse_wm_density():
    override, physical = parse_wm_density("Physical density: 420\nOverride density: 360\n")
    assert override == 360
    assert physical == 420


def test_parse_battery():
    text = "level: 87\ntemperature: 315\nvoltage: 4301\nstatus: 2\nhealth: 2\nAC powered: true\n"
    battery = parse_battery(text)
    assert battery.level == 87
    assert battery.temperature_c == 31.5
    assert battery.voltage_mv == 4301
    assert battery.ac is True


def test_parse_props():
    text = "[ro.product.model]: [Pixel 7]\n[ro.build.version.sdk]: [34]\n"
    props = parse_props(text)
    assert props["ro.product.model"] == "Pixel 7"
    assert props["ro.build.version.sdk"] == "34"
