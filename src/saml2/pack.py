#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2010-2011 Umeå University
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#            http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Contains classes and functions that are necessary to implement 
different bindings.

Bindings normally consists of three parts:
- rules about what to send 
- how to package the information
- which protocol to use
"""
import urlparse
import saml2
import base64
import urllib
from saml2.s_utils import deflate_and_base64_encode
import logging

logger = logging.getLogger(__name__)

try:
    from xml.etree import cElementTree as ElementTree
    if ElementTree.VERSION < '1.3.0':
        # cElementTree has no support for register_namespace
        # neither _namespace_map, thus we sacrify performance
        # for correctness
        from xml.etree import ElementTree
except ImportError:
    try:
        import cElementTree as ElementTree
    except ImportError:
        from elementtree import ElementTree

NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/"
FORM_SPEC = """<form method="post" action="%s">
   <input type="hidden" name="%s" value="%s" />
   <input type="hidden" name="RelayState" value="%s" />
   <input type="submit" value="Submit" />
</form>"""

def http_form_post_message(message, location, relay_state="", typ="SAMLRequest"):
    """The HTTP POST binding defines a mechanism by which SAML protocol 
    messages may be transmitted within the base64-encoded content of a
    HTML form control.
    
    :param message: The message
    :param location: Where the form should be posted to
    :param relay_state: for preserving and conveying state information
    :return: A tuple containing header information and a HTML message.
    """
    response = ["<head>", """<title>SAML 2.0 POST</title>""", "</head><body>"]

    if not isinstance(message, basestring):
        message = "%s" % (message,)
        
    response.append(FORM_SPEC % (location, typ, base64.b64encode(message),
                                relay_state))
                                
    response.append("""<script type="text/javascript">""")
    response.append("     window.onload = function ()")
    response.append(" { document.forms[0].submit(); }")
    response.append("""</script>""")
    response.append("</body>")
    
    return [("Content-type", "text/html")], response

#noinspection PyUnresolvedReferences
def http_post_message(message, location, relay_state="", typ="SAMLRequest"):
    """

    :param message:
    :param location:
    :param relay_state:
    :param typ:
    :return:
    """
    return [("Content-type", "text/xml")], message

def http_redirect_message(message, location, relay_state="", typ="SAMLRequest"):
    """The HTTP Redirect binding defines a mechanism by which SAML protocol 
    messages can be transmitted within URL parameters.
    Messages are encoded for use with this binding using a URL encoding 
    technique, and transmitted using the HTTP GET method. 
    
    The DEFLATE Encoding is used in this function.
    
    :param message: The message
    :param location: Where the message should be posted to
    :param relay_state: for preserving and conveying state information
    :return: A tuple containing header information and a HTML message.
    """
    
    if not isinstance(message, basestring):
        message = "%s" % (message,)
        
    args = {typ: deflate_and_base64_encode(message)}
    
    if relay_state:
        args["RelayState"] = relay_state

    glue_char = "&" if urlparse.urlparse(location).query else "?"
    login_url = glue_char.join([location, urllib.urlencode(args)])
    headers = [('Location', login_url)]
    body = [""]
    
    return headers, body

DUMMY_NAMESPACE = "http://example.org/"
PREFIX = '<?xml version="1.0" encoding="UTF-8"?>'

def make_soap_enveloped_saml_thingy(thingy, header_parts=None):
    """ Returns a soap envelope containing a SAML request
    as a text string.

    :param thingy: The SAML thingy
    :return: The SOAP envelope as a string
    """
    envelope = ElementTree.Element('')
    envelope.tag = '{%s}Envelope' % NAMESPACE

    if header_parts:
        header = ElementTree.Element('')
        header.tag = '{%s}Header' % NAMESPACE
        envelope.append(header)
        for part in header_parts:
            part.become_child_element_of(header)

    body = ElementTree.Element('')
    body.tag = '{%s}Body' % NAMESPACE
    envelope.append(body)

    if isinstance(thingy, basestring):
        thingy = thingy.replace(PREFIX, "")
        _child = ElementTree.Element('')
        _child.tag = '{%s}FuddleMuddle' % DUMMY_NAMESPACE
        body.append(_child)
        _str = ElementTree.tostring(envelope, encoding="UTF-8")
        # find an remove the namespace definition
        i = _str.find(DUMMY_NAMESPACE)
        j = _str.rfind("xmlns:", 0, i)
        cut1 = _str[j:i+len(DUMMY_NAMESPACE)+1]
        cut2 = "<%s:FuddleMuddle />" % (cut1[6:9],)
        _str = _str.replace(cut1, "")
        return _str.replace(cut2,thingy)
    else:
        thingy.become_child_element_of(body)
        return ElementTree.tostring(envelope, encoding="UTF-8")

def http_soap_message(message):
    return ([("Content-type", "application/soap+xml")],
            make_soap_enveloped_saml_thingy(message))
    
def http_paos(message, extra=None):
    return ([("Content-type", "application/soap+xml")],
            make_soap_enveloped_saml_thingy(message, extra))
    
def parse_soap_enveloped_saml(text, body_class, header_class=None):
    """Parses a SOAP enveloped SAML thing and returns header parts and body

    :param text: The SOAP object as XML 
    :return: header parts and body as saml.samlbase instances
    """
    envelope = ElementTree.fromstring(text)
    assert envelope.tag == '{%s}Envelope' % NAMESPACE

    #print len(envelope)
    body = None
    header = {}
    for part in envelope:
        #print ">",part.tag
        if part.tag == '{%s}Body' % NAMESPACE:
            for sub in part:
                try:
                    body = saml2.create_class_from_element_tree(body_class, sub)
                except Exception:
                    raise Exception(
                            "Wrong body type (%s) in SOAP envelope" % sub.tag)
        elif part.tag == '{%s}Header' % NAMESPACE:
            if not header_class:
                raise Exception("Header where I didn't expect one")
            #print "--- HEADER ---"
            for sub in part:
                #print ">>",sub.tag
                for klass in header_class:
                    #print "?{%s}%s" % (klass.c_namespace,klass.c_tag)
                    if sub.tag == "{%s}%s" % (klass.c_namespace, klass.c_tag):
                        header[sub.tag] = \
                            saml2.create_class_from_element_tree(klass, sub)
                        break
                        
    return body, header

# -----------------------------------------------------------------------------

PACKING = {
    saml2.BINDING_HTTP_REDIRECT: http_redirect_message,
    saml2.BINDING_HTTP_POST: http_form_post_message,
    }
    
def packager( identifier ):
    try:
        return PACKING[identifier]
    except KeyError:
        raise Exception("Unkown binding type: %s" % identifier)
