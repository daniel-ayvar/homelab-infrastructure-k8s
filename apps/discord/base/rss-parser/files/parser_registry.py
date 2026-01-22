import parser_dokkaninfo
import parser_hytale
import parser_placeholder
import parser_pokemon_zone

PARSER_MAP = {
    "dokkaninfo": parser_dokkaninfo.build_items,
    "hytale": parser_hytale.build_items,
    "placeholder": parser_placeholder.build_items,
    "pokemon-zone": parser_pokemon_zone.build_items,
}


def build_items(feed: dict, parser: dict):
    parser_type = parser.get("type", "placeholder")
    handler = PARSER_MAP.get(parser_type, parser_placeholder.build_items)
    return handler(feed, parser)
