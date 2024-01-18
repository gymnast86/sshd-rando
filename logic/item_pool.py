from constants.itemconstants import *
from .settings import *
from .item import *

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .world import World


class ItemPoolError(RuntimeError):
    pass


# Generates the item pool for a single world
# Items being placed in vanilla or restricted
# location sets will be filtered out later. Items
# that need to be removed and not placed anywhere
# will be removed now
def generate_item_pool(world: "World") -> None:
    item_pool = STANDARD_ITEM_POOL

    match world.setting("item_pool"):
        case "minimal":
            item_pool = MINIMAL_ITEM_POOL
        case "standard":
            item_pool = STANDARD_ITEM_POOL
        case "extra":
            item_pool = EXTRA_ITEM_POOL
        case "plentiful":
            item_pool = PLENTIFUL_ITEM_POOL

    # Remove Key Pieces if the ET Door is open
    if world.setting("open_earth_temple") == "on":
        item_pool = [item for item in item_pool if item != KEY_PIECE]

    if world.setting("small_keys") == "removed":
        item_pool = [
            item
            for item in item_pool
            if not item.endswith(SMALL_KEY) or item == LC_SMALL_KEY
        ]

    if world.setting("lanayru_caves_key") == "removed":
        item_pool.remove(LC_SMALL_KEY)

    if world.setting("boss_keys") == "removed":
        item_pool = [item for item in item_pool if not item.endswith(BOSS_KEY)]

    for item_name in item_pool:
        item = world.get_item(item_name)
        world.item_pool[item] += 1


# Will remove items from the passed in world's item pool
# and add them to the starting pool.
def generate_starting_item_pool(world: "World"):
    starting_items = world.setting_map.starting_inventory
    invalid_starting_items = starting_items

    # Verify starting_inventory setting is valid
    # Doesn't include would-be valid items (like swords) since those are
    # dealt with with a separate setting
    for item in STARTABLE_ITEMS:
        if item in invalid_starting_items:
            invalid_starting_items[item] = invalid_starting_items[item] - 1

            if invalid_starting_items[item] == 0:
                del invalid_starting_items[item]

    if invalid_starting_items.total() > 0:
        for item in invalid_starting_items:
            starting_items[item] -= invalid_starting_items[item]
            logging.getLogger("").debug(
                f"Removed {invalid_starting_items[item]} copies of {item} from the starting item pool."
            )

        print(
            f"WARNING: Invalid starting items found. The invalid entries have been removed. Invalid starting items: {invalid_starting_items}"
        )

    # Add starting swords
    starting_sword_setting = world.setting_map.settings.get("starting_sword")

    if starting_sword_setting:
        starting_items[PROGRESSIVE_SWORD] = starting_sword_setting.current_option_index

    for item_name, count in starting_items.items():
        item = world.get_item(item_name)
        world.starting_item_pool[item] += count
        world.item_pool[item] -= count

    # If all three parts of the song of the hero are in the starting inventory
    # replace them with just the singular song of the hero
    all_soth_parts = {
        FARON_SOTH_PART,
        ELDIN_SOTH_PART,
        LANAYRU_SOTH_PART,
    }
    if all(world.get_item(part) in world.starting_item_pool for part in all_soth_parts):
        for part in all_soth_parts:
            part_item = world.get_item(part)
            world.starting_item_pool[part_item] = 0
        world.starting_item_pool[world.get_item(SONG_OF_THE_HERO)] = 1


def get_random_junk_item_name():
    return random.choice([RED_RUPEE, SILVER_RUPEE, UNCOMMON_TREASURE, RARE_TREASURE])


def get_complete_item_pool(worlds: list["World"]) -> list[Item]:
    complete_item_pool: list[Item] = []
    for world in worlds:
        for item, count in world.item_pool.items():
            complete_item_pool.extend([item] * count)
    return complete_item_pool
