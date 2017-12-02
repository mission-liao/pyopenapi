from __future__ import absolute_import
from ...spec.base import NullContext
from ...scan import Dispatcher
from ...errs import SchemaError
from ...utils import scope_compose, get_or_none
from ...consts import private
from ...spec.v1_2.objects import (
    ResourceListing,
    ApiDeclaration,
    Operation,
    Authorization,
    Parameter,
    Model,
)
from ...spec.v2_0.objects import Swagger
import os
import six


def _get_name(path):
    return path.split('/', 3)[2]


def update_type_and_ref(dst, src, scope, sep, app):
    ref = getattr(src, '$ref')
    if ref:
        dst['$ref'] = '#/definitions/' + scope_compose(scope, ref, sep=sep)

    if app.prim_factory.is_primitive(getattr(src, 'type', None)):
        dst['type'] = src.type.lower()
    elif src.type:
        dst['$ref'] = '#/definitions/' + scope_compose(scope, src.type, sep=sep)

def convert_min_max(dst, src):
    def _from_str(name):
        v = getattr(src, name, None)
        if v:
            if src.type == 'integer':
                # we need to handle 1.0 when converting to int
                # that's why we need to convert to float first
                dst[name] = int(float(v))
            elif src.type == 'number':
                dst[name] = float(v)
            else:
                raise SchemaError('minimum/maximum is only allowed on integer/number, not {0}'.format(src.type))
        else:
            dst.pop(name, None)

    _from_str('minimum')
    _from_str('maximum')


def convert_schema_from_datatype(obj, scope, sep, app):
    if obj == None:
        return None

    spec = {}
    update_type_and_ref(spec, obj, scope, sep, app)
    spec['format'] = obj.format
    if obj.is_set('defaultValue'):
        spec['default'] = obj.defaultValue
    convert_min_max(spec, obj)
    spec['uniqueItems'] = obj.uniqueItems
    spec['enum'] = obj.enum
    if obj.items:
        item_spec = {}
        update_type_and_ref(item_spec, obj.items, scope, sep, app)
        item_spec['format'] = obj.items.format
        spec['items'] = item_spec

    return spec

def convert_items(o, app):
    items_spec = {}
    if getattr(o, '$ref'):
        raise SchemaError('Can\'t have $ref for Items')
    if not app.prim_factory.is_primitive(getattr(o, 'type', None)):
        raise SchemaError('Non primitive type is not allowed for Items')
    items_spec['type'] = o.type.lower()
    items_spec['format'] = o.format

    return items_spec

def convert_parameter(param, scope, sep, app):
    p_spec = {}
    p_spec['name'] = param.name
    p_spec['required'] = param.required
    p_spec['description'] = param.description

    if param.paramType == 'form':
        p_spec['in'] = 'formData'
    else:
        p_spec['in'] = param.paramType

    if 'body' == p_spec['in']:
        p_spec['schema'] = convert_schema_from_datatype(param, scope, sep, app)
    else:
        if getattr(param, '$ref'):
            raise SchemaError('Can\'t have $ref in non-body Parameters')

        if param.allowMultiple == True and param.items == None:
            p_spec['type'] = 'array'
            p_spec['collectionFormat'] = 'csv'
            p_spec['uniqueItems'] = param.uniqueItems
            p_spec['items'] = convert_items(param, app)
            if param.is_set("defaultValue"):
                p_spec['default'] = [param.defaultValue]
            p_spec['items']['enum'] = param.enum
        else:
            p_spec['type'] = param.type.lower()
            p_spec['format'] = param.format
            if param.is_set("defaultValue"):
                p_spec['default'] = param.defaultValue
            convert_min_max(p_spec, param)
            p_spec['enum'] = param.enum

        if param.items:
            p_spec['collectionFormat'] = 'csv'
            p_spec['uniqueItems'] = param.uniqueItems
            p_spec['items'] = convert_items(param.items, app)

    return p_spec

def convert_operation(op, api, api_decl, swagger, sep, app):
    op_spec = {}

    scope = api_decl.resourcePath[1:]
    op_spec['tags'] = [scope]
    op_spec['operationId'] = op.nickname
    op_spec['summary'] = op.summary
    op_spec['description'] = op.notes
    op_spec['deprecated'] = op.deprecated == 'true'

    c = op.consumes if op.consumes else api_decl.consumes
    op_spec['consumes'] = c if c else []

    p = op.produces if op.produces else api_decl.produces
    op_spec['produces'] = p if p else []

    parameters = op_spec.setdefault('parameters', [])
    for p in op.parameters:
        parameters.append(convert_parameter(p, scope, sep, app))
    op_spec['security'] = []

    # if there is not authorizations in this operation,
    # looking for it in api-declaration object.
    _auth = op.authorizations if op.authorizations else api_decl.authorizations
    if _auth:
        for name, scopes in six.iteritems(_auth):
            op_spec['security'].append({name: [v.scope for v in scopes]})

    # Operation return value
    op_spec['responses'] = {}
    resp_spec = {}
    if op.type != 'void':
        resp_spec['schema'] = convert_schema_from_datatype(op, scope, sep, app)
    resp_spec['description'] = '' # description is a required field in 2.0 Response object
    op_spec['responses']['default'] = resp_spec

    path = api_decl.base_path + api.path
    if path not in swagger['paths']:
        swagger['paths'][path] = {}

    method = op.method.lower()
    swagger['paths'][path][method] = op_spec


class Upgrade(object):
    """ convert 1.2 object to 2.0 object
    """
    class Disp(Dispatcher): pass

    def __init__(self, sep=private.SCOPE_SEPARATOR):
        self.__swagger = None
        self.__sep = sep

    @Disp.register([ResourceListing])
    def _resource_listing(self, path, obj, app):
        swagger_spec = {}
        swagger_spec['swagger'] = '2.0'
        swagger_spec['schemes'] = ['http', 'https']
        swagger_spec['host'] = ''
        swagger_spec['basePath'] = ''
        swagger_spec['tags'] = []
        swagger_spec['definitions'] = {}
        swagger_spec['parameters'] = {}
        swagger_spec['responses'] = {}
        swagger_spec['paths'] = {}
        swagger_spec['security'] = []
        swagger_spec['securityDefinitions'] = {}
        swagger_spec['consumes'] = []
        swagger_spec['produces'] = []

        #   Info Object
        info_spec = {}
        info_spec['version'] = obj.apiVersion
        info_spec['title'] = get_or_none(obj, 'info', 'title')
        info_spec['description'] = get_or_none(obj, 'info', 'description')
        info_spec['termsOfService'] = get_or_none(obj, 'info', 'termsOfServiceUrl')

        #       Contact Object
        if obj.info.contact:
            contact_spec = {}
            contact_spec['email'] = get_or_none(obj, 'info', 'contact')
            info_spec['contact'] = contact_spec
        #       License Object
        if obj.info.license or obj.info.licenseUrl:
            license_spec = {}
            license_spec['name'] = get_or_none(obj, 'info', 'license')
            license_spec['url'] = get_or_none(obj, 'info', 'licenseUrl')
            info_spec['license'] = license_spec

        swagger_spec['info'] = info_spec

        self.__swagger = swagger_spec

    @Disp.register([ApiDeclaration])
    def _api_declaration(self, path, obj, app):
        name = obj.resource_path[1:]
        for t in self.__swagger['tags']:
            if t['name'] == name:
                break
        else:
            tag_spec = {}
            tag_spec['name'] = name
            self.__swagger['tags'].append(tag_spec)

        for api in obj.apis:
            for op in api.operations:
                convert_operation(op, api, obj, self.__swagger, self.__sep, app)

    @Disp.register([Authorization])
    def _authorization(self, path, obj, app):
        ss_spec = {}
        if obj.type == 'basicAuth':
            ss_spec['type'] = 'basic'
        else:
            ss_spec['type'] = obj.type
        ss_spec['scopes'] = {}
        for s in obj.scopes or []:
            ss_spec['scopes'][s.scope] = s.description

        if ss_spec['type'] == 'oauth2':
            ss_spec['authorizationUrl'] = get_or_none(obj, 'grantTypes', 'implicit', 'loginEndpoint', 'url')
            ss_spec['tokenUrl'] = get_or_none(obj, 'grantTypes', 'authorization_code', 'tokenEndpoint', 'url')
            if ss_spec['authorizationUrl']:
                ss_spec['flow'] = 'implicit'
            elif o.tokenUrl:
                ss_spec['flow'] = 'access_code'
        elif ss_spec['type'] == 'apiKey':
            ss_spec['name'] = obj.keyname
            o.update_field('in', obj.passAs)

        self.__swagger['securityDefinitions'][_get_name(path)] = ss_spec

    @Disp.register([Model])
    def _model(self, path, obj, app):
        scope = _get_name(path)

        # Ex. a 'Status' model under 'Pet' resource
        # => new model-id would be 'Pet##Status'
        s = scope_compose(scope, obj.id, sep=self.__sep)
        s_spec = self.__swagger['definitions'].setdefault(s, {})

        props = {}
        for name, prop in six.iteritems(obj.properties):
            props[name] = convert_schema_from_datatype(prop, scope, self.__sep, app)
            props[name]['description'] = prop.description

        s_spec.setdefault('properties', {}).update(props)

        s_spec['required'] = obj.required
        s_spec['discriminator'] = obj.discriminator
        s_spec['description'] = obj.description

        for t in obj.subTypes or []:
            # here we assume those child models belongs to
            # the same resource.
            sub_s = scope_compose(scope, t, sep=self.__sep)
            sub_o_spec = self.__swagger['definitions'].setdefault(sub_s, {})

            new_ref = {}
            new_ref['$ref'] = '#/definitions/' + s
            sub_o_spec.setdefault('allOf', []).append(new_ref)

    def get_swagger(self):
        """ some preparation before returning Swagger object
        """
        # prepare Swagger.host & Swagger.basePath
        if not self.__swagger:
            return None

        common_path = os.path.commonprefix(list(self.__swagger['paths'].keys()))
        # remove tailing slash,
        # because all paths in Paths Object would prefixed with slah.
        common_path = common_path[:-1] if common_path[-1] == '/' else common_path

        if len(common_path) > 0:
            p = six.moves.urllib.parse.urlparse(common_path)
            self.__swagger['host'] = p.netloc

            new_common_path = six.moves.urllib.parse.urlunparse((
                p.scheme, p.netloc, '', '', '', ''))
            new_path = {}
            for k in self.__swagger['paths'].keys():
                new_path[k[len(new_common_path):]] = self.__swagger['paths'][k]
            self.__swagger['paths'] = new_path

        return Swagger(self.__swagger, '#')

