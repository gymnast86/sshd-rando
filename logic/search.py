import logging
from collections import Counter
from .item import *
from .area import *
from .search_mode import SearchMode

from gui.dialogs.dialog_header import print_progress_text, update_progress_value

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .world import *


class Search:
    def __init__(
        self,
        search_mode_: int,
        worlds_: list["World"],
        items_: Iterable[Item] = [],
        world_to_search_: int = -1,
        importance_location_: Location = None,
    ) -> None:
        self.search_mode: int = search_mode_
        self.worlds: list["World"] = worlds_
        self.world_to_search: int = world_to_search_

        # Search variables
        self.sphere_num: int = 0
        self.new_things_found: bool = True
        self.is_beatable: bool = False
        self.collect_items: bool = True
        self.owned_events: set[int] = set()
        self.owned_items: Counter[Item] = Counter(items_)

        self.events_to_try: list[EventAccess] = []
        self.exits_to_try: list[Entrance] = []
        self.visited_locations: set[Location] = set()
        self.visited_areas: set[Area] = set()
        self.successful_exits: set[Entrance] = set()
        self.playthrough_entrances: set[Entrance] = set()
        self.found_disconnected_exit: bool = False

        self.playthrough_spheres: list[list[Location]] = []
        self.entrance_spheres: list[list[Entrance]] = []

        self.area_time: dict[int, int] = {}

        # Variables used for Location Importance searches
        self.items_at_start: Counter[Item] = Counter(items_)
        self.only_search_with_items_at_start: bool = False
        self.assumed_wallet_capacity: int = 0
        self.assumed_crystal_count: int = 0
        self.assumed_false_req: Requirement = Requirement(RequirementType.IMPOSSIBLE)
        self.importance_location: Location = importance_location_

        # Add starting inventory items for each world
        for world in self.worlds:
            if world.id == self.world_to_search or self.world_to_search == -1:
                for item, count in world.starting_item_pool.items():
                    self.owned_items[item] += count
                    self.items_at_start[item] += count

        # Set search starting properties and add each world's root to exits_to_try
        for world in self.worlds:
            if world.id == self.world_to_search or self.world_to_search == -1:
                root = world.root
                self.visited_areas.add(root)
                world.set_search_starting_properties(self)
                for root_exit in root.exits:
                    if not root_exit.disabled:
                        self.exits_to_try.append(root_exit)
                    # Don't add non root exits if we're doing a sphere zero search
                    if self.search_mode == SearchMode.SPHERE_ZERO:
                        break

        # If we're doing an importance search, then we have to setup a few extra things
        if self.search_mode == SearchMode.LOCATION_IMPORTANCE:
            importance_item = self.importance_location.current_item

            # Generate the logic requirement for what it would "mean" to obtain the item at this importance location
            # We're going to assume that this logic requirement is always false when searching.
            # This ensures that we only evaluate to true the chain locations that this item absolutely does not help unlock
            count = self.owned_items[importance_item] + 1
            if count == 1:
                self.assumed_false_req = Requirement(
                    RequirementType.ITEM, [importance_item]
                )
            else:
                self.assumed_false_req = Requirement(
                    RequirementType.COUNT, [count, importance_item]
                )

            # If this location is either a wallet or gratitude crystals, we'll pass along any assumed wallet capacity or
            # gratitude crystal count from this location or any of its path locations. This will properly take into account any
            # wallet or crystal requirements that were necessary to get here and adjust hint importance accordingly.
            # (I.e. If Beedle 1600 is a path location, and this location has a wallet, then it'll always be not required.)
            if importance_item.is_same_or_similar_item(
                importance_item.world.get_item(PROGRESSIVE_WALLET)
            ):
                self.assumed_wallet_capacity = (
                    self.importance_location.computed_requirement.get_wallet_capacity()
                )
                for loc in self.importance_location.path_locations:
                    self.assumed_wallet_capacity = max(
                        self.assumed_wallet_capacity,
                        loc.computed_requirement.get_wallet_capacity(),
                    )

            if importance_item.is_same_or_similar_item(
                importance_item.world.get_item(GRATITUDE_CRYSTAL)
            ):
                self.assumed_crystal_count = (
                    self.importance_location.computed_requirement.get_crystal_count()
                )
                for loc in self.importance_location.path_locations:
                    self.assumed_crystal_count = max(
                        self.assumed_crystal_count,
                        loc.computed_requirement.get_crystal_count(),
                    )

    def search_worlds(self) -> None:
        # Get all locations which fit criteria to test on each iteration
        item_locations: list[LocationAccess] = []
        for world in self.worlds:
            for area in world.areas.values():
                for loc_access in area.locations:
                    if not loc_access.location.is_empty() or self.search_mode in [
                        SearchMode.ACCESSIBLE_LOCATIONS,
                        SearchMode.ALL_LOCATIONS_REACHABLE,
                        SearchMode.SPHERE_ZERO,
                        SearchMode.TRACKER_SPHERES,
                    ]:
                        item_locations.append(loc_access)

        # Main Searching Loop
        # Keep iterating while new things are being found, but
        # if the search is beatable and we're either generating
        # the playthrough or checking for beatability, exit early
        self.new_things_found = True
        while self.new_things_found and not (
            self.is_beatable
            and self.search_mode
            in [SearchMode.GENERATE_PLAYTHROUGH, SearchMode.GAME_BEATABLE]
        ):
            # Variable to keep track of making logical progress. We want to keep
            # looping as long as we're finding new things on each iteration
            self.new_things_found = False

            # Add an empty sphere if we're generating the playthrough or tracker spheres
            if self.search_mode in [
                SearchMode.GENERATE_PLAYTHROUGH,
                SearchMode.TRACKER_SPHERES,
            ]:
                self.playthrough_spheres.append([])
                self.entrance_spheres.append([])

            self.process_events()
            self.process_exits()

            # For proper sphere calculation based on item locations
            # we need to keep looping over exits and events until
            # nothing new is found in them (and then process locations)
            while (
                self.search_mode
                in [SearchMode.GENERATE_PLAYTHROUGH, SearchMode.TRACKER_SPHERES]
                and self.new_things_found
            ):
                self.new_things_found = False
                self.process_events()
                self.process_exits()

            self.process_locations(item_locations)

            self.sphere_num += 1

    # Explore the given area, and recursively explore the area's connected to it as
    # well if they haven't been visited yet.
    def explore(self, area: Area) -> None:
        for event in area.events:
            self.events_to_try.append(event)

        for exit_ in area.exits:
            eval_success = evaluate_exit_requirement(self, exit_)
            match eval_success:
                case EvalSuccess.COMPLETE:
                    self.successful_exits.add(exit_)
                    self.add_exit_to_entrance_spheres(exit_)
                    if exit_.connected_area not in self.visited_areas:
                        self.visited_areas.add(exit_.connected_area)
                        self.explore(exit_.connected_area)
                case EvalSuccess.PARTIAL:
                    self.exits_to_try.append(exit_)
                    self.add_exit_to_entrance_spheres(exit_)
                    if exit_.connected_area not in self.visited_areas:
                        self.visited_areas.add(exit_.connected_area)
                        self.explore(exit_.connected_area)
                case EvalSuccess.NONE:
                    self.exits_to_try.append(exit_)
                case EvalSuccess.UNNECESSARY:
                    self.found_disconnected_exit = True

    def process_exits(self) -> None:
        # Search each exit in the exitsToTry list and explore any new areas found as well.
        # For any exits which we try and don't meet the requirements for, put them
        # into exitsToTry for the next iteration.
        for exit_ in self.exits_to_try:
            # Ignore the exit if it we've already completed it, or we're not searching
            # its world at the moment
            if exit_ in self.successful_exits or (
                self.world_to_search != -1 and self.world_to_search != exit_.world.id
            ):
                continue

            eval_success = evaluate_exit_requirement(self, exit_)
            if eval_success == EvalSuccess.UNNECESSARY:
                self.successful_exits.add(exit_)
            elif eval_success in [EvalSuccess.COMPLETE, EvalSuccess.PARTIAL]:
                self.add_exit_to_entrance_spheres(exit_)
                if eval_success == EvalSuccess.COMPLETE:
                    self.successful_exits.add(exit_)

                self.new_things_found = True

                # If this exit's connected region hasn't been explored yet, then explore it
                if exit_.connected_area not in self.visited_areas:
                    self.visited_areas.add(exit_.connected_area)
                    self.explore(exit_.connected_area)

    # Loop through and see if there are any events that are now accessible.
    # Add them to the ownedEvents list if they are.
    def process_events(self) -> None:
        for event in self.events_to_try:
            # Ignore the event if it isn't part of the world we're searching or we already found it
            if event.id in self.owned_events or (
                self.world_to_search != -1
                and event.area.world.id != self.world_to_search
            ):
                continue

            if evaluate_event_requirement(self, event) == EvalSuccess.COMPLETE:
                self.new_things_found = True
                self.owned_events.add(event.id)

    def process_locations(self, item_locations: list[LocationAccess]) -> None:
        accessible_this_iteration: list[Location] = []
        for loc_access in item_locations:
            loc = loc_access.location
            world = loc_access.area.world

            if (
                loc in self.visited_locations
                or loc_access.area not in self.visited_areas
                or (self.world_to_search != -1 and world.id != self.world_to_search)
            ):
                continue

            if evaluate_location_requirement(self, loc_access) == EvalSuccess.COMPLETE:
                self.visited_locations.add(loc)
                self.new_things_found = True
                if self.search_mode in [
                    SearchMode.GENERATE_PLAYTHROUGH,
                    SearchMode.TRACKER_SPHERES,
                ]:
                    accessible_this_iteration.append(loc)
                else:
                    self.process_location(loc)

        for location in accessible_this_iteration:
            self.process_location(location)
            if self.is_beatable:
                return

    def process_location(self, location: Location) -> None:
        if not self.collect_items or (
            self.search_mode == SearchMode.LOCATION_IMPORTANCE
            and self.importance_location.current_item.is_same_or_similar_item(
                location.current_item
            )
        ):
            return
        if self.search_mode == SearchMode.TRACKER_SPHERES:
            self.owned_items[location.tracked_item] += 1
        else:
            self.owned_items[location.current_item] += 1
        if (
            self.search_mode == SearchMode.GENERATE_PLAYTHROUGH
            and location.current_item.is_major_item
            or self.search_mode == SearchMode.TRACKER_SPHERES
        ):
            self.playthrough_spheres[-1].append(location)

        # If we're generating a playthrough or just checking for beatability then we can
        # stop searching early by checking if we've found all game beating items for each
        # world
        if (
            self.search_mode
            in [SearchMode.GENERATE_PLAYTHROUGH, SearchMode.GAME_BEATABLE]
            and location.current_item.is_game_winning_item
        ):
            if len(
                [item for item in self.owned_items if item.is_game_winning_item]
            ) == len(self.worlds):
                # If this is the playthrough, and we've found all game winning items, clear the current sphere
                # except for the last game winning items
                if self.search_mode == SearchMode.GENERATE_PLAYTHROUGH:
                    self.playthrough_spheres[-1] = [
                        loc
                        for loc in self.playthrough_spheres[-1]
                        if loc.current_item.is_game_winning_item
                    ]
                self.is_beatable = True

    def add_exit_to_entrance_spheres(self, exit_: Entrance) -> None:
        if (
            self.search_mode
            in [SearchMode.GENERATE_PLAYTHROUGH, SearchMode.TRACKER_SPHERES]
            and exit_.shuffled
        ):
            if exit_ not in self.playthrough_entrances:
                self.entrance_spheres[-1].append(exit_)
                self.playthrough_entrances.add(exit_)
                if not exit_.decoupled and exit_.replaces.reverse:
                    self.playthrough_entrances.add(exit_.replaces.reverse)

    def remove_empty_spheres(self) -> None:
        spheres_to_remove = []
        for i in range(len(self.playthrough_spheres)):
            if (
                len(self.playthrough_spheres[i]) == 0
                and len(self.entrance_spheres[i]) == 0
            ):
                spheres_to_remove.append(i)

        # Remove spheres from higher indices first so we the lower
        # indices stay the same
        for index in reversed(spheres_to_remove):
            self.playthrough_spheres.pop(index)
            self.entrance_spheres.pop(index)

    # Will return all areas which have a non-impossible connection
    # from the root of the world graph
    def get_all_connected_areas(self) -> set[Area]:
        found_areas = set()
        area_queue: list[Area] = [world.root for world in self.worlds]

        while len(area_queue) > 0:
            area = area_queue.pop(0)

            for entrance in area.exits:
                if entrance.requirement.type == RequirementType.IMPOSSIBLE:
                    continue
                if connected_area := entrance.connected_area:
                    if connected_area not in found_areas:
                        area_queue.append(connected_area)
                        found_areas.add(connected_area)

        return found_areas

    # Will dump a file which can be turned into a visual graph using graphviz
    # https://graphviz.org/download/
    # Use this command to generate the graph: dot -Tsvg <filename> -o world.svg
    # Then, open world.svg in a browser and CTRL + F to find the area of interest
    def dump_world_graph(self, world_num: int = 0, filename: str = "World"):
        world = self.worlds[world_num]
        with open(filename + ".gv", "w", encoding="utf-8") as world_graph:
            world_graph.write("digraph {\n\tcenter=true;\n")

            for area_id, area in world.areas.items():
                color = '"black"' if area in self.visited_areas else '"red"'
                tod_str = ":<br/>"
                if area_id in self.area_time:
                    if self.area_time[area_id] & TOD.DAY:
                        tod_str += " Day"
                    if self.area_time[area_id] & TOD.NIGHT:
                        tod_str += " Night"

                world_graph.write(
                    f'\t"{area}"[label=<{area}{tod_str}> shape="plain" fontcolor={color}];\n'
                )

                # Make edge connections defined by events
                for event in area.events:
                    color = '"blue"' if event.id in self.owned_events else '"red"'
                    event_name = world.reverse_events[event.id]
                    world_graph.write(
                        f'\t"{event_name}"[label=<{event_name}> shape="plain" fontcolor={color}];'
                    )
                    world_graph.write(
                        f'\t"{area}" -> "{event_name}"[dir=forward color={color}]'
                    )

                # Make edge connections defined by exits
                for exit_ in area.exits:
                    if exit_.connected_area != None:
                        color = '"black"' if exit_ in self.successful_exits else '"red"'
                        world_graph.write(
                            f'\t"{area}" -> "{exit_.connected_area}"[dir=forward color={color}]'
                        )

                # Make edge connections between areas and their locations:
                for loc_access in area.locations:
                    loc = loc_access.location
                    color = '"black"' if loc in self.visited_locations else '"red"'
                    world_graph.write(
                        f'\t"{loc}"[label=<{loc}:<br/>{loc.current_item}> shape="plain" fontcolor={color}];'
                    )
                    world_graph.write(
                        f'\t"{area}" -> "{loc}"[dir=forward color={color}]'
                    )

            world_graph.write("}")


def game_beatable(worlds: list["World"], item_pool: list[Item] = []) -> bool:
    search = Search(SearchMode.GAME_BEATABLE, worlds, item_pool)
    search.search_worlds()
    return search.is_beatable


# Checks to see if each world's logic setting is currently satisfied
def all_logic_satisfied(worlds: list["World"], item_pool: Counter[Item] = {}) -> bool:
    search = Search(SearchMode.ALL_LOCATIONS_REACHABLE, worlds, item_pool)
    search.search_worlds()
    for world in worlds:
        if world.setting("logic_rules") == "all_locations_reachable":
            visited_world_locations = [
                l for l in search.visited_locations if l.world == world
            ]
            if len(visited_world_locations) != len(world.location_table):
                print(
                    "Missing locations:\n",
                    [
                        loc.name
                        for loc in world.location_table.values()
                        if loc not in visited_world_locations
                    ],
                )
                # Special case for minimal item pool as it removes 2 beetles
                # and locks access to the Ancient Harbour crown rupees and the
                # Pirate Stronghold pillar rupees
                if world.setting("item_pool") == "minimal":
                    missing_locs = [
                        loc.name
                        for loc in world.location_table.values()
                        if loc not in visited_world_locations
                        and "Allowed Unreachable" not in loc.types
                    ]

                    if len(missing_locs) > 0:
                        print(f"Could not reach these locations: {missing_locs}")
                    else:
                        continue

                return False
        elif world.setting("logic_rules") == "beatable_only":
            # We want to make sure that enough goal locations are still reachable for selecting
            # required dungeons later. Remove goal locations that are irrelevant.
            accessible_goal_locations = [
                l
                for l in world.location_table.values()
                if l.is_goal_location
                and l in search.visited_locations
                and (
                    world.setting("dungeons_include_sky_keep") == "on"
                    or not l.name.startswith("Sky Keep")
                )
            ]

            # Filter so that there's only one sky keep goal location
            found_sky_keep_goal = False
            for loc in accessible_goal_locations.copy():
                if "Sky Keep" in loc.name and not found_sky_keep_goal:
                    found_sky_keep_goal = True
                elif "Sky Keep" in loc.name and found_sky_keep_goal:
                    accessible_goal_locations.remove(loc)

            if (
                world.get_game_winning_item() not in search.owned_items
                or len(accessible_goal_locations)
                < world.setting("required_dungeons").value_as_number()
            ):
                return False

    return True


def generate_playthrough(worlds: list["World"]) -> None:
    logging.getLogger("").debug("Generating Playthrough")
    # Generate initial playthrough
    playthrough_search = Search(SearchMode.GENERATE_PLAYTHROUGH, worlds)
    playthrough_search.search_worlds()

    playthrough_spheres = playthrough_search.playthrough_spheres

    # Keep track of all locations we temporarily take items away from
    # so we can give them back after playthrough calculation
    temp_empty_locations = {}
    # Keep track of all the locations that appear in the playthrough
    playthrough_locations_set: set[Location] = set(
        [l for sphere in playthrough_spheres for l in sphere]
    )

    # Remove all items from locations that are not part of the playthrough set
    for location in [l for world in worlds for l in world.location_table.values()]:
        if location not in playthrough_locations_set:
            temp_empty_locations[location] = location.current_item
            location.remove_current_item()

    print_progress_text("Paring down playthrough")
    # Reverse the playthrough so we're paring it down from highest to lowest sphere
    # This way, lower sphere items will be prioritized for the playthrough
    for sphere in reversed(playthrough_spheres):
        for location in sphere:
            item_at_location = location.current_item
            location.remove_current_item()

            # If the game is beatable, temporarily take this item away and
            # discard the location to the set of playthrough locations
            if game_beatable(worlds):
                temp_empty_locations[location] = item_at_location
                playthrough_locations_set.discard(location)
            else:
                location.set_current_item(item_at_location)

    # Now generate a new playthrough search incase some spheres were flattened
    # by the previous generation having access to extra items
    new_search = Search(SearchMode.GENERATE_PLAYTHROUGH, worlds)
    new_search.search_worlds()

    # Now do the same process for entrances to pare down the entrance playthrough
    entrance_spheres = new_search.entrance_spheres
    non_required_entrances = {}

    for sphere in entrance_spheres:
        for entrance in sphere.copy():
            connected_area = entrance.disconnect()
            if game_beatable(worlds):
                # If the game is still beatable then this entrance is not required
                sphere.remove(entrance)
                non_required_entrances[entrance] = connected_area
            else:
                # If the entrance is required, reconnect it
                entrance.connect(connected_area)

    # Reconnect all non-required entrances
    for entrance, connected_area in non_required_entrances.items():
        entrance.connect(connected_area)

    # Give locations back their items
    for location, item in temp_empty_locations.items():
        location.set_current_item(item)

    # Discard all locations not in the playthrough locations set
    for sphere in new_search.playthrough_spheres:
        for location in sphere.copy():
            if location not in playthrough_locations_set:
                sphere.discard(location)

    # Now remove any empty spheres that might remain
    new_search.remove_empty_spheres()

    worlds[0].playthrough_spheres = new_search.playthrough_spheres
    worlds[0].entrance_spheres = new_search.entrance_spheres


# Returns all the possible gossip stones that could
# hint at the passed in location
def get_possible_gossip_stones(location: Location) -> list[Location]:
    item_at_location = location.current_item
    location.remove_current_item()

    search = Search(SearchMode.ACCESSIBLE_LOCATIONS, location.world.worlds)
    search.search_worlds()

    location.set_current_item(item_at_location)
    stones = location.world.get_gossip_stones()
    return [stone for stone in stones if stone in search.visited_locations]
