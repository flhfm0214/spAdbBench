from adbtool.services.packages import (
    GOOGLE_PACKAGES,
    PackageInfo,
    PackageService,
    filter_packages,
    parse_foreground,
    parse_package_listing,
    parse_pm_path,
)


def sample_listing():
    return (
        "__ADBTOOL_ALL__\n"
        "package:com.android.settings\n"
        "package:com.example.app\n"
        "package:com.google.android.gms\n"
        "__ADBTOOL_DISABLED__\n"
        "package:com.google.android.gms\n"
        "__ADBTOOL_SYSTEM__\n"
        "package:com.android.settings\n"
        "package:com.google.android.gms\n"
        "__ADBTOOL_END__\n"
    )


def test_parse_package_listing_merges_disabled_and_system():
    packages = parse_package_listing(sample_listing())
    by_name = {p.package: p for p in packages}

    assert by_name["com.android.settings"].system is True
    assert by_name["com.android.settings"].enabled is True
    assert by_name["com.example.app"].system is False
    assert by_name["com.google.android.gms"].enabled is False


def test_parse_foreground():
    text = (
        "mResumedActivity: ActivityRecord{123 u0 com.example.app/.MainActivity t42}\n"
        "topResumedActivity=ActivityRecord{456 u0 com.android.settings/.Settings t43}\n"
    )
    package, activity = parse_foreground(text)
    assert package == "com.example.app"
    assert activity == ".MainActivity"


def test_parse_pm_path():
    text = "package:/data/app/base.apk\npackage:/data/app/split_config.arm64_v8a.apk\n"
    assert parse_pm_path(text) == [
        "/data/app/base.apk",
        "/data/app/split_config.arm64_v8a.apk",
    ]


def test_action_commands_are_safe():
    assert PackageService.action_command("disable", "com.example.app") == (
        "pm disable-user --user 0 com.example.app"
    )
    assert PackageService.action_command("uninstall_keep", "com.example.app") == (
        "pm uninstall -k com.example.app"
    )
    assert PackageService.action_command("enable", "com.example.app") == (
        "pm enable com.example.app"
    )
    assert PackageService.action_command("restore", "com.example.app") == (
        "pm install-existing --user 0 com.example.app; pm enable com.example.app"
    )


def test_action_command_rejects_bad_package():
    import pytest

    with pytest.raises(ValueError):
        PackageService.action_command("disable", "com.example; rm -rf /")


def test_restart_command_force_stops_then_launches():
    assert PackageService.restart_command("com.example.app") == (
        "am force-stop com.example.app; "
        "monkey -p com.example.app -c android.intent.category.LAUNCHER 1"
    )


def test_restart_command_rejects_bad_package():
    import pytest

    with pytest.raises(ValueError):
        PackageService.restart_command("com.example; reboot")


def test_filter_packages():
    packages = [
        PackageInfo("com.android.settings", enabled=True, system=True),
        PackageInfo("com.example.app", enabled=True, system=False),
        PackageInfo("com.google.android.gms", enabled=False, system=True),
    ]

    assert [p.package for p in filter_packages(packages, "", "third")] == ["com.example.app"]
    assert [p.package for p in filter_packages(packages, "", "system")] == [
        "com.android.settings",
        "com.google.android.gms",
    ]
    assert [p.package for p in filter_packages(packages, "google", "all")] == [
        "com.google.android.gms"
    ]
    assert [p.package for p in filter_packages(packages, "", "disabled")] == [
        "com.google.android.gms"
    ]


def test_google_candidates_respects_state():
    packages = [
        PackageInfo("com.google.android.gms", enabled=False, system=True),
        PackageInfo("com.android.vending", enabled=True, system=True),
        PackageInfo("com.example.app", enabled=True, system=False),
    ]
    assert PackageService.google_candidates(packages, enable=False) == ["com.android.vending"]
    assert PackageService.google_candidates(packages, enable=True) == ["com.google.android.gms"]


def test_google_package_list_has_core_entries():
    assert "com.google.android.gms" in GOOGLE_PACKAGES
    assert "com.android.vending" in GOOGLE_PACKAGES
