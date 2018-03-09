from __future__ import absolute_import
import copy
import six


def attr(key, required=False, default=None):
    """ property factory for attributes

    Args:
     - key: the key to access this field in internal dict in 'AttributeGroup'
     - required: if this field is required, would raise exception if corresponding field doesn't
                 existed in internal dict
     - default: default value to return when corresponding field doesn't existed in internal dict
    """

    def _getter_(self):
        if key in self.attrs:
            return self.attrs[key]
        if required:
            raise Exception('attribute not found: {} in {}'.format(
                key, self.__class__.__name__))
        return default

    def _setter_(self, v):
        self.attrs[key] = v

    return property(_getter_, _setter_)


class AttributeMeta(type):
    """ metaclass to init attributes
    """

    def __new__(metacls, name, bases, spec):
        attrs = spec.setdefault('__attributes__', {})

        for n, args in six.iteritems(attrs):
            args = copy.copy(args)
            builder = args.pop('builder', None) or attr
            spec[n] = builder(args.pop('key', None) or n, **args)

        return type.__new__(metacls, name, bases, spec)


class _Attrs(object):
    """ You can attach attributes to a Base2Obj. It provides a mechanism to
    keep runtime info to an OpenApi objects. Example usage is 'ref_obj' for
    'Reference' object.
    """

    def __init__(self, attrs={}):
        self.attrs = attrs


AttributeGroup = six.with_metaclass(AttributeMeta, _Attrs)
