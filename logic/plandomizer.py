from filepathconstants import ENTRANCE_SHUFFLE_DATA_PATH
from pathlib import Path
from .world import *
import yaml


class PlandomizerError(RuntimeError):
    pass


def load_plandomizer_data(worlds: list[World], filepath: Path):
    if filepath == None:
        return
    if not filepath.is_file():
        raise PlandomizerError(f"Could not find plandomizer file: {filepath}")

    with open(filepath, "r", encoding="utf-8") as plando_file:
        plando = yaml.safe_load(plando_file)

        # Load plando data for all worlds
        for world in worlds:
            world_str = f"{world}"
            if world_str not in plando:
                continue
            world_data = plando[world_str]

            if "locations" in world_data:
                for location, item in world_data["locations"].items():
                    # If the item is a string, use it directly
                    if type(item) is str:
                        world.plandomizer_locations[world.get_location(location)] = (
                            world.get_item(item)
                        )
                    else:
                        # If the item isn't a string, then it should have world and item specifications
                        for field in ["world", "item"]:
                            if field not in item:
                                raise PlandomizerError(
                                    f"The item being plandomized at {location} in {world} is missing the {field} field"
                                )

                        # Throw an error if the specified world number doesn't exist
                        if item["world"] > len(worlds):
                            raise PlandomizerError(
                                f'Incorrect world number "{item["world"]}". Only {len(worlds)} world(s) are being generated.'
                            )

                        world.plandomizer_locations[world.get_location(location)] = (
                            worlds[item["world"] - 1].get_item(item["item"])
                        )

            if "entrances" in world_data:
                alias_dict = load_entrance_aliases()
                for entrance_name, target_name in world_data["entrances"].items():
                    # Get proper names if aliases were used
                    if entrance_name in alias_dict:
                        entrance_name = alias_dict[entrance_name]
                    if target_name in alias_dict:
                        target_name = alias_dict[target_name]
                        target_parent, target_connected = target_name.split(" -> ")
                    else:
                        target_connected, target_parent = target_name.split(" from ")

                    entrance = world.get_entrance(entrance_name)
                    target = world.get_entrance(
                        f"{target_parent} -> {target_connected}"
                    )

                    world.plandomizer_entrances[entrance] = target

            if "sometimes_hint_locations" in world_data:
                # Clear previous sometimes locations
                for location in world.get_all_item_locations():
                    if location.hint_priority == "sometimes":
                        location.hint_priority = "never"

                for location_name in world_data["sometimes_hint_locations"]:
                    location = world.get_location(location_name)
                    location.hint_priority = "sometimes"

            if "always_hint_locations" in world_data:
                # Clear previous always locations
                for location in world.get_all_item_locations():
                    if location.hint_priority == "always":
                        location.hint_priority = "never"

                for location_name in world_data["always_hint_locations"]:
                    location = world.get_location(location_name)
                    location.hint_priority = "always"


# Helper function to load entrance aliases since they aren't normally loaded until setting entrance data
def load_entrance_aliases() -> dict[str, str]:
    alias_dict: dict[str, str] = {}
    with open(ENTRANCE_SHUFFLE_DATA_PATH, encoding="utf-8") as entrance_data_file:
        entrance_shuffle_list = yaml.safe_load(entrance_data_file)
        for entrance_data in entrance_shuffle_list:
            original_name = entrance_data["forward"]["connection"]
            if alias := entrance_data["forward"].get("alias", None):
                alias_reverse_format = " from ".join(reversed(alias.split(" -> ")))
                alias_dict[alias] = original_name
                alias_dict[alias_reverse_format] = original_name

            if "return" in entrance_data:
                return_name = entrance_data["return"]["connection"]
                if alias := entrance_data["return"].get("alias", None):
                    alias_reverse_format = " from ".join(reversed(alias.split(" -> ")))
                    alias_dict[alias] = return_name
                    alias_dict[alias_reverse_format] = return_name

    return alias_dict
