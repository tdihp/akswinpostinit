from .base import Action


class ReadyAction(Action):
    """always backoff until node becomes ready"""
    def is_ready(self, node):
        return any(
            (condition.type == 'Ready' and condition.status == "True")
            for condition in node.status.conditions)

    def is_done(self, node):
        return self.is_ready(node)

    def is_in_backoff(self, node):
        return not self.is_ready(node)
