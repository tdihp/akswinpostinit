JSONPATH_TRANSLATE_TABLE = str.maketrans({'~': '~0', '/': '~1'})


def jsonpath_escape(s):
    """escape jsonpath for generating jsonpath patches.
    
    'foo/bar~' --> 'foo~1bar~0'
    """
    return s.translate(JSONPATH_TRANSLATE_TABLE)
