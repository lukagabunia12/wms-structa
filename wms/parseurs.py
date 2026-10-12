"""Le corps JSON d'une requête doit être un objet.

Chaque vue lit des champs par leur nom (`request.data.get("place")`). Un corps
qui était une liste — `["enzo"]` — arrivait jusqu'à elle, et `.get` levait une
AttributeError : une erreur 500 pour une requête simplement mal formée. On la
refuse à l'entrée, en 400, avec une phrase.
"""
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class ObjetJSON(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        donnees = super().parse(stream, media_type, parser_context)
        if not isinstance(donnees, dict):
            raise ParseError("Le corps de la requête doit être un objet JSON { … }.")
        return donnees

