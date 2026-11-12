"""Configuration-driven dispatch with mandatory approval floors."""
from copy import deepcopy
from creditwatch import catalog


class ActionPolicy:
    def __init__(self, config):
        config = deepcopy(config)
        self.classes = config["tool_classes"]
        self.policies = config["class_policies"]
        self.overrides = config.get("overrides", {})
        problems = catalog.conformance(self.classes)
        if set(self.policies) != set(catalog.POLICY):
            problems.append("class_policies must cover the six action classes exactly")
        if set(self.overrides) - set(catalog.CATALOG):
            problems.append("unknown tool override")
        for name, (action_class, _) in catalog.CATALOG.items():
            actual = self.overrides.get(name, self.policies.get(action_class))
            minimum = catalog.policy_for(name)
            if actual not in {minimum, "forbidden"}:
                problems.append(f"{name}: must use {minimum} or forbidden")
        if self.policies.get("DESTRUCTIVE") != "forbidden":
            problems.append("destructive actions must remain forbidden")
        if problems:
            raise ValueError("Invalid action_policy: " + "; ".join(problems))

    def mode(self, name):
        return self.overrides.get(name, self.policies[self.classes[name]])
