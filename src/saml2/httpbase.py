from Cookie import SimpleCookie
import cookielib
import copy
import requests
import time
from saml2 import class_name
from saml2.pack import http_form_post_message
from saml2.pack import make_soap_enveloped_saml_thingy
from saml2.pack import http_redirect_message

import logging
from saml2.soap import parse_soap_enveloped_saml_response

logger = logging.getLogger(__name__)

__author__ = 'rolandh'

ATTRS = {"version":None,
         "name":"",
         "value": None,
         "port": None,
         "port_specified": False,
         "domain": "",
         "domain_specified": False,
         "domain_initial_dot": False,
         "path": "",
         "path_specified": False,
         "secure": False,
         "expires": None,
         "discard": True,
         "comment": None,
         "comment_url": None,
         "rest": "",
         "rfc2109": True}

PAIRS = {
    "port": "port_specified",
    "domain": "domain_specified",
    "path": "path_specified"
}

class ConnectionError(Exception):
    pass

def _since_epoch(cdate):
    # date format 'Wed, 06-Jun-2012 01:34:34 GMT'
    cdate = cdate[5:-4]
    try:
        t = time.strptime(cdate, "%d-%b-%Y %H:%M:%S")
    except ValueError:
        t = time.strptime(cdate, "%d-%b-%y %H:%M:%S")
    return int(time.mktime(t))

class HTTPBase(object):
    def __init__(self, verify=True, ca_bundle=None, key_file=None,
                 cert_file=None):
        self.request_args = {"allow_redirects": False,}
        self.cookies = {}
        self.cookiejar = cookielib.CookieJar()

        self.request_args["verify"] = verify
        if ca_bundle:
            self.request_args["verify"] = ca_bundle
        if key_file:
            self.request_args["cert"] = (cert_file, key_file)
        
        self.sec = None
        
    def _cookies(self):
        cookie_dict = {}

        for _, a in list(self.cookiejar._cookies.items()):
            for _, b in list(a.items()):
                for cookie in list(b.values()):
                    # print cookie
                    cookie_dict[cookie.name] = cookie.value

        return cookie_dict

    def set_cookie(self, kaka, request):
        """Returns a cookielib.Cookie based on a set-cookie header line"""

        # default rfc2109=False
        # max-age, httponly
        for cookie_name, morsel in kaka.items():
            std_attr = ATTRS.copy()
            std_attr["name"] = cookie_name
            _tmp = morsel.coded_value
            if _tmp.startswith('"') and _tmp.endswith('"'):
                std_attr["value"] = _tmp[1:-1]
            else:
                std_attr["value"] = _tmp

            std_attr["version"] = 0
            # copy attributes that have values
            for attr in morsel.keys():
                if attr in ATTRS:
                    if morsel[attr]:
                        if attr == "expires":
                            std_attr[attr]=_since_epoch(morsel[attr])
                        else:
                            std_attr[attr]=morsel[attr]
                elif attr == "max-age":
                    if morsel["max-age"]:
                        std_attr["expires"] = _since_epoch(morsel["max-age"])

            for att, set in PAIRS.items():
                if std_attr[att]:
                    std_attr[set] = True

            if std_attr["domain"] and std_attr["domain"].startswith("."):
                std_attr["domain_initial_dot"] = True

            if morsel["max-age"] is 0:
                try:
                    self.cookiejar.clear(domain=std_attr["domain"],
                                         path=std_attr["path"],
                                         name=std_attr["name"])
                except ValueError:
                    pass
            else:
                new_cookie = cookielib.Cookie(**std_attr)

                self.cookiejar.set_cookie(new_cookie)

    def send(self, url, method="GET", **kwargs):
        _kwargs = copy.copy(self.request_args)
        if kwargs:
            _kwargs.update(kwargs)

        if self.cookiejar:
            _kwargs["cookies"] = self._cookies()
            #logger.info("SENT COOKIEs: %s" % (_kwargs["cookies"],))
        try:
            r = requests.request(method, url, **_kwargs)
        except requests.ConnectionError, exc:
            raise ConnectionError("%s" % exc)

        try:
            #logger.info("RECEIVED COOKIEs: %s" % (r.headers["set-cookie"],))
            self.set_cookie(SimpleCookie(r.headers["set-cookie"]), r)
        except AttributeError, err:
            pass

        return r

    def use_http_form_post(self, message, destination, relay_state):
        """
        Return a form that will automagically execute and POST the message
        to the recipient.

        :param message:
        :param destination:
        :param relay_state:
        :return: tuple (header, message)
        """
        if not isinstance(message, basestring):
            request = "%s" % (message,)

        return http_form_post_message(message, destination, relay_state)


    def use_http_get(self, message, destination, relay_state):
        """
        Send a message using GET, this is the HTTP-Redirect case so
        no direct response is expected to this request.

        :param request:
        :param destination:
        :param relay_state:
        :return: tuple (header, None)
        """
        if not isinstance(message, basestring):
            request = "%s" % (message,)

        return http_redirect_message(message, destination, relay_state)

    def send_using_soap(self, request, destination, headers=None, sign=False):
        """
        Send a message using SOAP+POST

        :param request:
        :param destination:
        :param headers:
        :param sign:
        :return:
        """
        if headers is None:
            headers = {"content-type": "application/soap+xml"}
        else:
            headers.update({"content-type": "application/soap+xml"})

        soap_message = make_soap_enveloped_saml_thingy(request)

        if sign and self.sec:
            _signed = self.sec.sign_statement_using_xmlsec(soap_message,
                                                           class_name(request),
                                                           nodeid=request.id)
            soap_message = _signed

        #_response = self.server.post(soap_message, headers, path=path)
        try:
            response = self.send(destination, "POST", data=soap_message,
                                 headers=headers)
        except Exception, exc:
            logger.info("HTTPClient exception: %s" % (exc,))
            return None

        if response:
            logger.info("SOAP response: %s" % response)
            return parse_soap_enveloped_saml_response(response)
        else:
            return False

