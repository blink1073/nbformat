# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.
"""
Common validator wrapper to provide a uniform usage of other schema validation
libraries.
"""

import os

import jsonschema
from jsonschema import Draft4Validator as _JsonSchemaValidator
from jsonschema import ErrorTree, ValidationError

try:
    import fastjsonschema
    from fastjsonschema import JsonSchemaException as _JsonSchemaException
except ImportError:
    fastjsonschema = None
    _JsonSchemaException = ValidationError


class JsonSchemaValidator:
    name = "jsonschema"

    def __init__(self, schema):
        self._schema = schema
        self._default_validator = _JsonSchemaValidator(schema)  # Default
        self._validator = self._default_validator

    def validate(self, data):
        self._default_validator.validate(data)

    def iter_errors(self, data, schema=None):
        if schema is None:
            return self._default_validator.iter_errors(data)
        if hasattr(self._default_validator, "evolve"):
            return self._default_validator.evolve(schema=schema).iter_errors(data)
        return self._default_validator.iter_errors(data, schema)

    def strip_invalid_metadata(self, data, errors):
        error_tree = ErrorTree(errors)
        stripped = False
        if "metadata" in error_tree:
            for key in error_tree["metadata"]:
                data["metadata"].pop(key, None)
                stripped = True

        if "cells" in error_tree:
            number_of_cells = len(data.get("cells", 0))
            for cell_idx in range(number_of_cells):
                # Cells don't report individual metadata keys as having failed validation
                # Instead it reports that it failed to validate against each cell-type definition.
                # We have to delve into why those definitions failed to uncover which metadata
                # keys are misbehaving.
                if "oneOf" in error_tree["cells"][cell_idx].errors:
                    intended_cell_type = data["cells"][cell_idx]["cell_type"]
                    schemas_by_index = [
                        ref["$ref"]
                        for ref in error_tree["cells"][cell_idx].errors["oneOf"].schema["oneOf"]
                    ]
                    cell_type_definition_name = f"#/definitions/{intended_cell_type}_cell"
                    if cell_type_definition_name in schemas_by_index:
                        schema_index = schemas_by_index.index(cell_type_definition_name)
                        for error in error_tree["cells"][cell_idx].errors["oneOf"].context:
                            rel_path = error.relative_path
                            error_for_intended_schema = error.schema_path[0] == schema_index
                            is_top_level_metadata_key = (
                                len(rel_path) == 2 and rel_path[0] == "metadata"
                            )
                            if error_for_intended_schema and is_top_level_metadata_key:
                                data["cells"][cell_idx]["metadata"].pop(rel_path[1], None)
                                stripped = True
        return stripped


class FastJsonSchemaValidator(JsonSchemaValidator):
    name = "fastjsonschema"

    def __init__(self, schema):
        super().__init__(schema)
        self._validator = fastjsonschema.compile(schema)

    def validate(self, data):
        try:
            self._validator(data)
        except _JsonSchemaException as error:
            raise ValidationError(str(error), schema_path=error.path)

    def iter_errors(self, data, schema=None):
        if schema is not None:
            return super().iter_errors(data, schema)

        errors = []
        validate_func = self._validator
        try:
            validate_func(data)
        except _JsonSchemaException as error:
            errors = [ValidationError(str(error), schema_path=error.path)]

        return errors

    def strip_invalid_metadata(self, data, errors):
        stripped = False
        for error in errors:
            section = data
            path = error.schema_path
            path.popleft()
            if "metadata" in path:
                while path[0] != "metadata":
                    section = section[path.popleft()]
                section = section["metadata"]
                section.pop(path[1], None)
                stripped = True
        return stripped


_VALIDATOR_MAP = [
    ("fastjsonschema", fastjsonschema, FastJsonSchemaValidator),
    ("jsonschema", jsonschema, JsonSchemaValidator),
]
VALIDATORS = [item[0] for item in _VALIDATOR_MAP]


def _validator_for_name(validator_name):
    if validator_name not in VALIDATORS:
        raise ValueError(
            f"Invalid validator '{validator_name}' value!\nValid values are: {VALIDATORS}"
        )

    for (name, module, validator_cls) in _VALIDATOR_MAP:
        if module and validator_name == name:
            return validator_cls


def get_current_validator():
    """
    Return the default validator based on the value of an environment variable.
    """
    default = "fastjsonschema" if fastjsonschema else "jsonschema"
    # default = "jsonschema"
    validator_name = os.environ.get("NBFORMAT_VALIDATOR", default)
    return _validator_for_name(validator_name)
