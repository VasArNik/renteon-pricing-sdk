from collections.abc import Mapping

""" 
Custom dictionary-like class. Get value from key or key from value, either direction.

"""
class BiDirectionalDictionary(Mapping):
    def __init__(self, data):
        self.forward = dict(data)
        self.reverse = {v: k for k, v in data.items()}

    def __repr__(self):
        return str(self.forward)

    def __getitem__(self, key):
        if key in self.forward:
            return self.forward[key]
        if key in self.reverse:
            return self.reverse[key]
        raise KeyError(key)

    def __iter__(self):
        return iter(self.forward)

    def __len__(self):
        return len(self.forward)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __setitem__(self, key, value):
        if key in self.forward:
            old_value = self.forward[key]
            del self.reverse[old_value]
        if value in self.reverse:
            old_key = self.reverse[value]
            del self.forward[old_key]

        self.forward[key] = value
        self.reverse[value] = key