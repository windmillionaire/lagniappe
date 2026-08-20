class WebFormSubmission:
    """Mock for Flask's request.form (ImmutableMultiDict)."""

    def __init__(self, submission):
        self.submission = submission

    def keys(self):
        return self.submission.keys()

    def get(self, field, default=None):
        return self.submission.get(field, default)

    def getlist(self, field):
        value = self.submission.get(field, None)
        if isinstance(value, list):
            return value
        elif value:
            return [str(value)]
        else:
            return []
