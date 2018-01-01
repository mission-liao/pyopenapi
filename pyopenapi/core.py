from __future__ import absolute_import
from .resolve import Resolver
from .cache import SpecObjCache
from .reloc import SpecObjReloc
from .primitives import Primitive, MimeCodec
from .spec.v1_2.objects import ResourceListing, ApiDeclaration
from .spec.v2_0.objects import Swagger, Operation
from .spec.v3_0_0.objects import OpenApi
from .scan import Scanner
from .scanner import TypeReduce, CycleDetector
from .scanner.v2_0 import Aggregate
from pyopenapi import utils, errs, consts
from distutils.version import StrictVersion
import copy
import base64
import six
import weakref
import logging
import pkgutil
import inspect


logger = logging.getLogger(__name__)


class App(object):
    """ Major component of pyopenapi

    This object is tended to be used in read-only manner. Therefore,
    all accessible attributes are almost read-only properties.
    """

    sc_path = 1

    _shortcut_ = {
        sc_path: ('/', '#/paths')
    }

    def __init__(self, url=None, url_load_hook=None, sep=consts.private.SCOPE_SEPARATOR, prim=None, mime_codec=None, resolver=None):
        """ constructor

        :param url str: url of swagger.json
        :param func url_load_hook: a way to redirect url to a accessible place. for self testing.
        :param sep str: separator used by pyswager.utils.ScopeDict
        :param prim pyopenapi.primitives.Primitive: factory for primitives in Swagger.
        :param resolver: pyopenapi.resolve.Resolver: customized resolver used as default when none is provided when resolving
        """

        logger.info('init with url: {0}'.format(url))

        self.__root = None
        self.__raw = None
        self.__original_spec_version = ''

        self.__op = None
        self.__m = None
        self.__schemes = []
        self.__url=url

        # a map from json-reference to
        # - spec.base2._Base
        # - a map from json-pointer to spec.base2._Base
        self.__cache = SpecObjCache()

        # a map from json-reference in older OpenApi spec
        # to json-reference in migrated OpenApi spec
        self.__reloc = SpecObjReloc()

        if url_load_hook and resolver:
            raise ValueError('when use customized Resolver, please pass url_load_hook to that one')

        # the start-point when you want to traverse the code to laod new object
        self.__resolver = resolver or Resolver(url_load_hook)

        # allow init App-wised SCOPE_SEPARATOR
        self.__sep = sep

        # init a default Primitive as factory for primitives
        self.__prim = prim if prim else Primitive()

        # MIME codec
        self.__mime_codec = mime_codec or MimeCodec()

    @property
    def sep(self):
        """ separator used by pyswager.utils.ScopeDict
        """
        return self.__sep

    @property
    def root(self):
        """ schema representation of Swagger API, its structure may
        be different from different version of Swagger.

        There is 'Schema' object in swagger 2.0, that's why I change this
        property name from 'schema' to 'root'.

        :type: pyopenapi.spec.v2_0.objects.Swagger
        """
        return self.__root

    @property
    def raw(self):
        """ raw objects for original version of loaded resources.
        When loaded json is the latest version we supported, this property is the same as App.root

        :type: ex. when loading Swagger 1.2, the type is pyopenapi.spec.v1_2.objects.ResourceList
        """
        return self.__raw

    @property
    def op(self):
        """ list of Operations, organized by utils.ScopeDict

        In Swagger 2.0, Operation(s) can be organized with Tags and Operation.operationId.
        ex. if there is an operation with tag:['user', 'security'] and operationId:get_one,
        here is the combination of keys to access it:
        - .op['user', 'get_one']
        - .op['security', 'get_one']
        - .op['get_one']

        :type: pyopenapi.utils.ScopeDict of pyopenapi.spec.v2_0.objects.Operation
        """
        return self.__op

    @property
    def m(self):
        """ backward compatible to access Swagger.definitions in Swagger 2.0,
        and Resource.Model in Swagger 1.2.

        ex. a Model:user in Resource:Users, access it by .m['Users', 'user'].
        For Schema object in Swagger 2.0, just access it by it key in json.

        :type: pyopenapi.utils.ScopeDict
        """
        return self.__m

    @property
    def version(self):
        """ original version of loaded json

        note: you should use 'original_spec_version' instead,
        this one is deprecated.

        :type: str
        """
        return self.__original_spec_version

    @property
    def original_spec_version(self):
        """ original spec version of loaded json

        :type: str
        """
        return self.__original_spec_version

    @property
    def current_spec_version(self):
        """ to which OpenApi spec version
        the loaded spec migrated to

        :type: str
        """
        return self.__current_spec_version

    @property
    def schemes(self):
        """ supported schemes, refer to Swagger.schemes in Swagger 2.0 for details

        :type: list of str, ex. ['http', 'https']
        """
        return self.__schemes

    @property
    def url(self):
        """
        """
        return self.__url

    @property
    def prim_factory(self):
        """ primitive factory used by this app

        :type: pyopenapi.primitives.Primitive
        """
        return self.__prim

    @property
    def mime_codec(self):
        """ mime codec used by this app

        :type: pyopenapi.primitives.MimeCodec
        """
        return self.__mime_codec

    @property
    def resolver(self):
        """ JSON Reference resolver

        :type: pyopenapi.resolve.Resolver
        """
        return self.__resolver

    @property
    def spec_obj_cache(self):
        """ Cache for Spec Objects

        :type: pyopenapi.cache.SpecObjCache
        """
        return self.__cache

    @property
    def spec_obj_reloc(self):
        """ map of relocation for Spec Objects

        :type: pyopenapi.reloc.SpecObjReloc
        """
        return self.__reloc

    def load_obj(self, jref, getter=None, parser=None, remove_dummy=False):
        """ load a object(those in spec._version_.objects) from a JSON reference.
        """
        src_spec = self.__resolver.resolve(jref, getter)

        # get root document to check its swagger version.
        obj = None
        version = utils.get_swagger_version(src_spec)
        url, jp = utils.jr_split(jref)

        # usually speaking, we would only enter App.load_obj when App.resolve
        # can't find the object. However, the 'version' in App.load_obj might
        # be different from the one passed into App.resolve.
        #
        # Therefore, we need to check the cache here again.
        obj = self.spec_obj_cache.get(url, jp, version)
        if obj:
            return obj, version

        override = self.spec_obj_cache.get_under(url, jp, version, remove=remove_dummy)
        if version == '1.2':
            obj = ResourceListing(src_spec, jref, {})

            resources = []
            for r in obj.apis:
                resources.append(r.path)

            base = utils.url_dirname(jref)
            urls = zip(
                map(lambda u: utils.url_join(base,  u[1:]), resources),
                map(lambda u: u[1:], resources)
            )

            cached_apis = {}
            for url, name in urls:
                resource_spec = self.resolver.resolve(url, getter)
                if resource_spec is None:
                    raise Exception('unable to resolve {} when load spec from {}'.format(url, jref))
                cached_apis[name] = ApiDeclaration(resource_spec, utils.jp_compose(name, base=url), {})

            obj.cached_apis = cached_apis

        # after Swagger 2.0, we need to handle
        # the loading order of external reference

        elif version == '2.0':
            # swagger 2.0
            obj = Swagger(src_spec, jref, override)

        elif version == '3.0.0':
            # openapi 3.0.0
            obj = OpenApi(src_spec, jref, override)

        elif version == None and parser:
            obj = parser(src_spec, jref, {})
            version = obj.__swagger_version__ if hasattr(obj, '__swagger_version__') else version
        else:
            raise NotImplementedError('Unsupported Swagger Version: {0} from {1}'.format(version, jref))

        if not obj:
            raise Exception('Unable to parse object from {0}'.format(jref))

        logger.info('version: {0}'.format(version))

        # cache obj before migration, or we may load an object multiple times when resolve
        # $ref in the same spec
        self.__cache.set(obj, url, jp, spec_version=version)

        return obj, version

    def prepare_obj(self, obj, jref, spec_version=None):
        """ basic preparation of an object(those in sepc._version_.objects),
        and cache the 'prepared' object.
        """
        if not obj:
            raise Exception('unexpected, passing {0}:{1} to prepare'.format(obj, jref))

        spec_version = spec_version or consts.private.DEFAULT_OPENAPI_SPEC_VERSION
        obj = self.migrate_obj(obj, jref, spec_version=spec_version)

        return obj

    def migrate_obj(self, obj, jref, spec_version=None):
        """ migrate an object(those in spec._version_.objects)
        """
        spec_version = spec_version or '3.0.0'
        supported_versions = utils.get_supported_versions('migration', is_pkg=False)

        if spec_version not in supported_versions:
            raise ValueError('unsupported spec version: {}'.format(spec_version))

        # only keep required version strings for this migration
        supported_versions = supported_versions[:(supported_versions.index(spec_version)+1)]

        # filter out those migration with lower version than current one
        supported_versions = [v for v in supported_versions if StrictVersion(obj.__swagger_version__) <= StrictVersion(v)]

        # load migration module
        url, jp = utils.jr_split(jref)
        for v in supported_versions:
            patched_version = 'v{}'.format(v).replace('.', '_')
            migration_module_path = '.'.join(['pyopenapi', 'migration', patched_version])
            loader = pkgutil.find_loader(migration_module_path)
            if not loader:
                raise Exception('unable to find module loader for {}'.format(migration_module_path))

            migration_module = loader.load_module(migration_module_path)
            if not migration_module:
                raise Exception('unable to load {} for migration'.format(migration_module_path))

            obj, reloc = migration_module.up(obj, self, jref)

            # update route for object relocation
            self.spec_obj_reloc.update(url, v, {jp: reloc})

            # cache migrated object if we need it later
            self.spec_obj_cache.set(obj, url, jp, spec_version=v)

        if isinstance(obj, (OpenApi, Swagger)):
            self.__current_spec_version = spec_version

        return obj

    def _validate(self):
        """ check if this Swagger API valid or not.

        :param bool strict: when in strict mode, exception would be raised if not valid.
        :return: validation errors
        :rtype: list of tuple(where, type, msg).
        """

        v_mod = utils.import_string('.'.join([
            'pyopenapi',
            'scanner',
            'v' + self.version.replace('.', '_'),
            'validate'
        ]))

        if not v_mod:
            # there is no validation module
            # for this version of spec
            return []

        s = Scanner(self)
        v = v_mod.Validate()

        s.scan(route=[v], root=self.__raw)
        return v.errs

    @classmethod
    def load(kls, url, getter=None, parser=None, url_load_hook=None, sep=consts.private.SCOPE_SEPARATOR, prim=None, mime_codec=None, resolver=None):
        """ load json as a raw App

        :param str url: url of path of Swagger API definition
        :param getter: customized Getter
        :type getter: sub class/instance of Getter
        :param parser: the parser to parse the loaded json.
        :type parser: pyopenapi.base.Context
        :param dict app_cache: the cache shared by related App
        :param func url_load_hook: hook to patch the url to load json
        :param str sep: scope-separater used in this App
        :param prim pyswager.primitives.Primitive: factory for primitives in Swagger
        :param mime_codec pyopenapi.primitives.MimeCodec: MIME codec
        :param resolver: pyopenapi.resolve.Resolver: customized resolver used as default when none is provided when resolving
        :return: the created App object
        :rtype: App
        :raises ValueError: if url is wrong
        :raises NotImplementedError: the swagger version is not supported.
        """

        logger.info('load with [{0}]'.format(url))

        url = utils.normalize_url(url)
        app = kls(url, url_load_hook=url_load_hook, sep=sep, prim=prim, mime_codec=mime_codec, resolver=resolver)
        app.__raw, app.__original_spec_version = app.load_obj(url, getter=getter, parser=parser)
        if app.__original_spec_version not in ['1.2', '2.0', '3.0.0']:
            raise NotImplementedError('Unsupported Version: {0}'.format(app.__version))

        # update schem if any
        p = six.moves.urllib.parse.urlparse(url)
        if p.scheme:
            app.schemes.append(p.scheme)

        return app

    def validate(self, strict=True):
        """ check if this Swagger API valid or not.

        :param bool strict: when in strict mode, exception would be raised if not valid.
        :return: validation errors
        :rtype: list of tuple(where, type, msg).
        """

        result = self._validate()
        if strict and len(result):
            for r in result:
                logger.error(r)
            raise errs.ValidationError('this Swagger App contains error: {0}.'.format(len(result)))

        return result

    def prepare(self, strict=True):
        """ preparation for loaded json

        :param bool strict: when in strict mode, exception would be raised if not valid.
        """

        self.validate(strict=strict)

        # extract schemes from the url to load spec
        self.__schemes = [six.moves.urllib.parse.urlparse(self.__url).scheme]

        self.__root = self.prepare_obj(self.raw, self.__url)

        # upadte schemes if available
        if isinstance(self.__root, Swagger) and hasattr(self.__root, 'schemes') and self.__root.schemes:
            self.__schemes = self.__root.schemes

        s = Scanner(self)
        s.scan(root=self.__root, route=[Aggregate()])

        # reducer for Operation
        tr = TypeReduce(self.__sep)
        cy = CycleDetector()
        s.scan(root=self.__root, route=[tr, cy])

        # 'op' -- shortcut for Operation with tag and operaionId
        self.__op = utils.ScopeDict(tr.op)
        # 'm' -- shortcut for model in Swagger 1.2
        if hasattr(self.__root, 'definitions') and self.__root.definitions != None:
            self.__m = utils.ScopeDict(self.__root.definitions)
        else:
            self.__m = utils.ScopeDict({})
        # update scope-separater
        self.__m.sep = self.__sep
        self.__op.sep = self.__sep

        # cycle detection
        if len(cy.cycles['schema']) > 0 and strict:
            raise errs.CycleDetectionError('Cycles detected in Schema Object: {0}'.format(cy.cycles['schema']))

    def migrate(self, spec_version=None):
        """ migrate the internal spec object (refer to pyopenapi.spec) to a specific version.
        This function can be used to migrate your original API spec to some version of OpenAPI,
        then dump to perform 'spec upgrade' action

        :param str spec_version: the version of OpenAPI you want to migrate, ex. 3.0.0, 'None' means latest version of OpenAPI
        """

        self.__root = self.migrate_obj(self.raw, self.url, spec_version=spec_version)

    @classmethod
    def create(kls, url, strict=True):
        """ factory of App

        :param str url: url of path of Swagger API definition
        :param bool strict: when in strict mode, exception would be raised if not valid.
        :return: the created App object
        :rtype: App
        :raises ValueError: if url is wrong
        :raises NotImplementedError: the swagger version is not supported.
        """
        app = kls.load(url)
        app.prepare(strict=strict)

        return app

    """ for backward compatible, for later version,
    please call App.create instead.
    """
    _create_ = create

    def resolve(self, jref, parser=None, spec_version=None, before_return=utils.final, remove_dummy=False):
        """ JSON reference resolver

        :param str jref: a JSON Reference, refer to http://tools.ietf.org/html/draft-pbryan-zyp-json-ref-03 for details.
        :param parser: the parser corresponding to target object.
        :param str spec_version: the OpenAPI spec version 'jref' pointing to.
        :param func before_return: a hook to patch object before returning it
        :param bool remove_dummy: a flag to tell pyopenapi to clean dummy objects in pyopenapi.spec_obj_cache
        :type parser: pyopenapi.base.Context
        :return: the referenced object, wrapped by weakref.ProxyType
        :rtype: weakref.ProxyType
        :raises ValueError: if path is not valid

        The initial intention for 'before_return' is to return obj.final_obj automatically.
        Prototype of this hook is:

            def your_hook(your_obj):
                # do something to 'your_obj'
                return your_obj
        """

        logger.info('resolving: [{0}]'.format(jref))

        if jref == None or len(jref) == 0:
            raise ValueError('Empty Path is not allowed')

        spec_version = spec_version or consts.private.DEFAULT_OPENAPI_SPEC_VERSION

        # check cacahed object against json reference by
        # comparing url first, and find those object prefixed with
        # the JSON pointer.
        url, jp = utils.jr_split(jref)
        obj = self.__cache.get(url, jp, spec_version)

        # this object is not found in cache
        if obj == None:
            if url:
                obj = self.load_obj(jref, parser=parser, remove_dummy=remove_dummy)
                if obj:
                    obj = self.prepare_obj(obj, jref, spec_version=spec_version)
            else:
                # a local reference, 'jref' is just a json-pointer
                if not jp.startswith('#'):
                    raise ValueError('Invalid Path, root element should be \'#\', but [{0}]'.format(jref))

                obj = self.root.resolve(utils.jp_split(jp)[1:]) # heading element is #, mapping to self.root

        if obj == None:
            raise ValueError('Unable to resolve path, [{0}]'.format(jref))

        if isinstance(obj, (six.string_types, six.integer_types, list, dict)):
            return obj

        if before_return:
            obj = before_return(obj)
        return weakref.proxy(obj)

    def s(self, p, b=_shortcut_[sc_path], before_return=utils.final):
        """ shortcut of App.resolve.
        We provide a default base for '#/paths'. ex. to access '#/paths/~1user/get',
        just call App.s('user/get')

        :param str p: path relative to base
        :param tuple b: a tuple (expected_prefix, base) to represent a 'base'
        """

        if b[0]:
            return self.resolve(utils.jp_compose(b[0] + p if not p.startswith(b[0]) else p, base=b[1]), before_return=before_return)
        else:
            return self.resolve(utils.jp_compose(p, base=b[1]), before_return=before_return)

    def dump(self):
        """ dump into Swagger Document

        :rtype: dict
        :return: dict representation of Swagger
        """
        return self.root.dump()



class Security(object):
    """ security handler
    """

    def __init__(self, app):
        """ constructor

        :param App app: App
        """
        self.__app = app

        # placeholder of Security Info
        self.__info = {}

    def update_with(self, name, security_info):
        """ insert/clear authorizations

        :param str name: name of the security info to be updated
        :param security_info: the real security data, token, ...etc.
        :type security_info: **(username, password)** for *basicAuth*, **token** in str for *oauth2*, *apiKey*.

        :raises ValueError: unsupported types of authorizations
        """
        s = self.__app.root.securityDefinitions.get(name, None)
        if s == None:
            raise ValueError('Unknown security name: [{0}]'.format(name))

        cred = security_info
        header = True
        if s.type == 'basic':
            cred = 'Basic ' + base64.standard_b64encode(six.b('{0}:{1}'.format(*security_info))).decode('utf-8')
            key = 'Authorization'
        elif s.type == 'apiKey':
            key = s.name
            header = getattr(s, 'in') == 'header'
        elif s.type == 'oauth2':
            key = 'access_token'
        else:
            raise ValueError('Unsupported Authorization type: [{0}, {1}]'.format(name, s.type))

        self.__info.update({name: (header, {key: cred})})

    def __call__(self, req):
        """ apply security info for a request.

        :param Request req: the request to be authorized.
        :return: the updated request
        :rtype: Request
        """
        if not req._security:
            return req

        for s in req._security:
            for k, v in six.iteritems(s):
                if not k in self.__info:
                    logger.info('missing: [{0}]'.format(k))
                    continue

                logger.info('applying: [{0}]'.format(k))

                header, cred = self.__info[k]
                if header:
                    req._p['header'].update(cred)
                else:
                    utils.nv_tuple_list_replace(req._p['query'], utils.get_dict_as_tuple(cred))

        return req


class BaseClient(object):
    """ base implementation of SwaggerClient, below is an minimum example
    to extend this class

    .. code-block:: python

        class MyClient(BaseClient):

            # declare supported schemes here
            __schemes__ = ['http', 'https']

            def request(self, req_and_resp, opt):
                # passing to parent for default patching behavior,
                # applying authorizations, ...etc.
                req, resp = super(MyClient, self).request(req_and_resp, opt)

                # perform request by req
                ...
                # apply result to resp
                resp.apply(header=header, raw=data_received, status=code)
                return resp
    """

    join_headers = 'join_headers'

    # supported schemes, ex. ['http', 'https', 'ws', 'ftp']
    __schemes__ = set()

    def __init__(self, security=None):
        """ constructor

        :param Security security: the security holder
        """

        # placeholder of Security
        self.__security = security

    def prepare_schemes(self, req):
        """ make sure this client support schemes required by current request

        :param pyopenapi.io.Request req: current request object
        """

        # fix test bug when in python3 scheme, more details in commint msg
        ret = sorted(self.__schemes__ & set(req.schemes), reverse=True)

        if len(ret) == 0:
            raise ValueError('No schemes available: {0}'.format(req.schemes))
        return ret

    def compose_headers(self, req, headers=None, opt=None, as_dict=False):
        """ a utility to compose headers from pyopenapi.io.Request and customized headers

        :return: list of tuple (key, value) when as_dict is False, else dict
        """
        if headers is None:
            return list(req.header.items()) if not as_dict else req.header

        opt = opt or {}
        join_headers = opt.pop(BaseClient.join_headers, None)
        if as_dict and not join_headers:
            # pick the most efficient way for special case
            headers = dict(headers) if isinstance(headers, list) else headers
            headers.update(req.header)
            return headers

        # include Request.headers
        aggregated_headers = list(req.header.items())

        # include customized headers
        if isinstance(headers, list):
            aggregated_headers.extend(headers)
        elif isinstance(headers, dict):
            aggregated_headers.extend(headers.items())
        else:
            raise Exception('unknown type as header: {}'.format(str(type(headers))))

        if join_headers:
            joined = {}
            for h in aggregated_headers:
                key = h[0]
                if key in joined:
                    joined[key] = ','.join([joined[key], h[1]])
                else:
                    joined[key] = h[1]
            aggregated_headers = list(joined.items())

        return dict(aggregated_headers) if as_dict else aggregated_headers

    def request(self, req_and_resp, opt=None, headers=None):
        """ preprocess before performing a request, usually some patching.
        authorization also applied here.

        :param req_and_resp: tuple of Request and Response
        :type req_and_resp: (Request, Response)
        :param opt: customized options
        :type opt: dict
        :param headers: customized headers
        :type headers: dict of 'string', or list of tuple: (string, string) for multiple values for one key
        :return: patched request and response
        :rtype: Request, Response
        """
        req, resp = req_and_resp

        # dump info for debugging
        logger.info('request.url: {0}'.format(req.url))
        logger.info('request.header: {0}'.format(req.header))
        logger.info('request.query: {0}'.format(req.query))
        logger.info('request.file: {0}'.format(req.files))
        logger.info('request.schemes: {0}'.format(req.schemes))

        # apply authorizations
        if self.__security:
            self.__security(req)

        return req, resp


SwaggerApp = App
SwaggerSecurity = Security

