from filepathconstants import DEFAULT_OUTPUT_PATH, PLANDO_PATH
from randomizer.setting_string import setting_string_from_config
from .world import World
from .config import *
from .settings import *
from .fill import fill_worlds
from .search import generate_playthrough
from .spoiler_log import generate_spoiler_log, generate_anti_spoiler_log
from .plandomizer import load_plandomizer_data
from .entrance_shuffle import shuffle_world_entrances
from .hints import generate_hints
from util.text import load_text_data

from gui.dialogs.dialog_header import print_progress_text, update_progress_value
import time
import random


def generate(config_file: Path) -> list[World]:
    get_all_settings_info()
    load_text_data()

    config = load_config_from_file(config_file, create_if_blank=True)

    if config.output_dir != DEFAULT_OUTPUT_PATH and (
        not config.output_dir.exists() or not config.output_dir.is_dir()
    ):
        raise ConfigError(
            f"""
The output folder you have specified cannot be found ({config.output_dir.as_posix()}).
Please choose a valid folder and try again."""
        )

    # If config has no seed, generate one
    if config.seed == "":
        config.seed = str(random.randint(0, 0xFFFFFFFF))
        # write_config_to_file(config_file, config)

    print_progress_text(f"Seed: {config.seed}")

    return generate_randomizer(config)


def generate_randomizer(config: Config) -> list[World]:
    start = time.process_time()

    seed_rng(config, resolve_non_standard_random=True, ignore_invalid_plandomizer=False)
    print(f"Hash: {config.get_hash()}")

    worlds: list[World] = []

    update_progress_value(2)

    # Build all necessary worlds
    for i in range(len(config.settings)):
        setting_map = config.settings[i]
        worlds.append(World(i))
        print_progress_text(f"Building {worlds[i]}")
        worlds[i].setting_map = setting_map
        worlds[i].resolve_random_settings()
        worlds[i].resolve_conflicting_settings()
        worlds[i].num_worlds = len(config.settings)
        worlds[i].config = config
        worlds[i].build()

    # Give each world a reference back to the list of all worlds
    for world in worlds:
        world.worlds = worlds

    print(
        f"Setting String: {setting_string_from_config(config, worlds[0].location_table)}"
    )

    # Process plando data for all worlds
    if config.use_plandomizer:
        if config.plandomizer_file is None:
            raise ConfigError(
                f"Cannot use plandomizer file as the current plandomizer filename is invalid: {config.plandomizer_file}"
            )

        load_plandomizer_data(worlds, PLANDO_PATH / config.plandomizer_file)

    # All worlds must perform pre-entrance shuffle tasks
    # before any entrance shuffling takes place
    for world in worlds:
        world.perform_pre_entrance_shuffle_tasks()

    update_progress_value(4)
    for world in worlds:
        print_progress_text(f"Shuffling entrances for {world}...")
        shuffle_world_entrances(world, worlds)

    for world in worlds:
        world.perform_post_entrance_shuffle_tasks()

    start = time.process_time()

    update_progress_value(6)
    print_progress_text("Filling Worlds...")

    fill_worlds(worlds)
    end = time.process_time()
    print(f"Fill took {(end - start)} seconds")

    for world in worlds:
        world.perform_post_fill_tasks()

    update_progress_value(8)
    generate_playthrough(worlds)

    update_progress_value(10)
    generate_hints(worlds)

    update_progress_value(12)
    if config.generate_spoiler_log:
        generate_spoiler_log(worlds)
    generate_anti_spoiler_log(worlds)
    return worlds
