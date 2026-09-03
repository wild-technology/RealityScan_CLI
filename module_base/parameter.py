class Parameter:
    name: str = None
    cli_short: str = None
    cli_long: str = None
    type: type = None
    value: object = None
    default_value: object = None
    explicit: bool = False
    description: str = None
    prompt_user: bool = None
    disable_when_module_active: str = None

    def __init__(self, name, cli_short, cli_long, type, default_value, description=None, prompt_user=True, disable_when_module_active=None):
        self.name = name
        self.cli_short = cli_short
        self.cli_long = cli_long
        self.value = default_value
        self.default_value = default_value
        self.description = description
        self.type = type
        self.prompt_user = prompt_user
        self.disable_when_module_active = disable_when_module_active
        # Nothing has been answered yet - this Parameter is holding its
        # declared default (see set_value).
        self.explicit = False
    
    def get_name(self) -> str:
        return self.name
    
    def get_type(self) -> type:
        return self.type

    def get_value(self) -> object:
        return self.value
    
    def set_value(self, value, explicit: bool = True) -> None:
        """Record a value, and whether it was actually SUPPLIED for this run.

        Assigning a value normally means someone answered, so ``explicit``
        defaults to True; pass False when installing the declared default
        as a fallback (main.parse_arguments is the one caller that knows -
        argparse's None for an absent flag is the last place the
        distinction survives). It CANNOT be recovered later by comparing
        value to default_value, because a supplied value is allowed to
        EQUAL the default: measured on NA168, --b_max_zone 4000 against a
        declared default of 4000 read as "not supplied", the stored
        batch.max_zone_size=8000 won, and a zone came out at 7,842 images
        against the 6,000 cap.
        """
        self.value = value
        self.explicit = explicit
    
    def is_explicit(self) -> bool:
        """Whether a value was SUPPLIED for this run, rather than falling
        back to ``default_value``."""
        return self.explicit

    def get_default_value(self) -> object:
        return self.default_value
    
    def get_description(self) -> str:
        return self.description