from pathlib import Path

import toml


def fix_global_config():
    """
    Fixes the 'general.email' error in the global Streamlit config.
    """
    home = Path.home()
    global_config_path = home / ".streamlit" / "config.toml"

    print(f"Checking global config at: {global_config_path}")

    if not global_config_path.exists():
        print("Global config not found. No fix needed.")
        return

    try:
        # Read content manually to preserve comments if possible, but TOML lib is safer for structure
        with open(global_config_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "[general]" not in content and "email" not in content:
            print("No 'general.email' found in global config.")
            return

        # Parse with toml
        config = toml.loads(content)

        changed = False
        if "general" in config:
            if "email" in config["general"]:
                print("Found 'general.email'. Removing...")
                del config["general"]["email"]
                changed = True

            # Remove empty [general] section
            if not config["general"]:
                del config["general"]
                changed = True

        if changed:
            with open(global_config_path, "w", encoding="utf-8") as f:
                toml.dump(config, f)
            print("Global config updated successfully!")
        else:
            print("Configuration appeared clean via TOML parser.")

    except Exception as e:
        print(f"Error fixing config: {e}")
        # Fallback: Manual string replacement if TOML lib fails or isn't installed
        try:
            with open(global_config_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = []
            skip_section = False
            for line in lines:
                stripped = line.strip()
                if stripped == "[general]":
                    skip_section = True
                    print("Removing [general] section via fallback...")
                    continue
                if skip_section and stripped.startswith("["):
                    skip_section = False

                if skip_section:
                    if stripped.startswith("email"):
                        continue

                new_lines.append(line)

            with open(global_config_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            print("Global config updated via fallback method.")

        except Exception as e2:
            print(f"Fallback failed: {e2}")

if __name__ == "__main__":
    # Ensure toml is installed (it usually is with streamlit)
    try:
        import toml
        fix_global_config()
    except ImportError:
        print("TOML module not found. Attempting fallback...")
        fix_global_config()
