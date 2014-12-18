"""LazyReference module.

This module contains functions, classes and mix-in that are used for the
building lazy references to objects located in database. These lazy references
will be evaluated only when some functions or properties will be called.

"""

import riak

from nova.db.discovery.models import get_model_class_from_name
from nova.db.discovery.models import get_model_classname_from_tablename

dbClient = riak.RiakClient(pb_port=8087, protocol='pbc')

def now_in_ms():
    return int(round(time.time() * 1000))

class EmptyObject:
    pass

class LazyReference:
    """Class that references a remote object stored in database. This aims
    easing the development of algorithm on relational objects: instead of
    populating relationships even when not required, we load them "only" when
    it is used!"""

    def __init__(self, base, id, desimplifier=None):
        """Constructor"""

        self.base = base
        self.id = id
        self.cache = {}

        if desimplifier is None:
            from desimplifier import ObjectDesimplifier
            self.desimplifier = ObjectDesimplifier()
        else:
            self.desimplifier = desimplifier

    def get_key(self):
        """Returns a unique key for the current LazyReference."""

        return "%s_%s" % (self.resolve_model_name(), str(self.id))

    def resolve_model_name(self):
        """Returns the model class corresponding to the remote object."""

        return get_model_classname_from_tablename(self.base)

    def spawn_empty_model(self, obj):
        """Spawn an empty instance of the model class specified by the
        given object"""

        key = self.get_key()

        if "novabase_classname" in obj:
            model_class_name = obj["novabase_classname"]
        elif "metadata_novabase_classname" in obj:
            model_class_name = obj["metadata_novabase_classname"]

        if model_class_name is not None:
            model = get_model_class_from_name(model_class_name)
            model_object = model()
            if not self.cache.has_key(key):
                self.cache[key] = model_object
            return self.cache[key]
        else:
            return None

    def update_nova_model(self, obj):
        """Update the fields of the given object."""

        key = self.get_key()
        current_model = self.cache[key]

        # Check if obj is simplified or not
        if "simplify_strategy" in obj:
            object_bucket = db_client.bucket(obj["tablename"])
            riak_value = object_bucket.get(str(obj["id"]))
            obj = riak_value.data

        # For each value of obj, set the corresponding attributes.
        for key in obj:
            simplified_value = self.desimplifier.desimplify(obj[key])
            try:
                if simplified_value is not None:
                    setattr(current_model, key, self.desimplifier.desimplify(obj[key]))
                else:
                    setattr(current_model, key, obj[key])
            except Exception as e:
                if "None is not list-like" in str(e):
                    setattr(current_model, key, [])
                else:
                    pass

        if hasattr(current_model, "user_id") and obj.has_key("user_id"):
            current_model.user_id = obj["user_id"]

        if hasattr(current_model, "project_id") and obj.has_key("project_id"):
            current_model.project_id = obj["project_id"]

        # Update foreign keys
        current_model.update_foreign_keys()

        return current_model

    def load(self):
        """Load the referenced object from the database. The result will be
        cached, so that next call will not create any database request."""

        key = self.get_key()

        key_index_bucket = dbClient.bucket(self.base)
        fetched = key_index_bucket.get(str(self.id))
        obj = fetched.data

        self.spawn_empty_model(obj)
        self.update_nova_model(obj)

        return self.cache[key]

    def get_complex_ref(self):
        """Return the python object that corresponds the referenced object. The
        first time this method has been invocked, a request to the database is
        made and the result is cached. The next times this method is invocked,
        the previously cached result is returned."""

        key = self.get_key()

        if not self.cache.has_key(key):
            self.load()

        return self.cache[key]


    def __getattr__(self, item):
        """This method 'intercepts' call to attribute/method on the referenced
        object: the object is thus loaded from database, and the requested
        attribute/method is then returned."""

        return getattr(self.get_complex_ref(), item)

    def __str__(self):
        """This method prevents the loading of the remote object when a
        LazyReference is printed."""

        return "Lazy(%s)" % (self.get_key())

    def __repr__(self):
        """This method prevents the loading of the remote object when a
        LazyReference is printed."""

        return "Lazy(%s)" % (self.get_key())

    def __nonzero__(self):
        """This method is required by some services of OpenStack."""

        return not not self.get_complex_ref()
