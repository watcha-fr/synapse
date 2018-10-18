import logging

from jinja2 import Template

logger = logging.getLogger(__name__)

# To avoid issues with setuptools/distutil,
# (not easy to get the 'res/templates' folder to be included in the whl file...)
# we ship the templates as .py files, and put them in the code tree itself.
# This is somewhat a hack, but it is somewhat suggested by the existence
# of a "PackagerLoader" in Jinja - they must have had the same issue :)

files = [
	'new_account.txt',
	'new_account.html',
	'reset_password.txt',
	'reset_password.html',
	'invite_new_account.txt',
	'invite_new_account.html',
	'invite_existing_account.txt',
	'invite_existing_account.html',
]

TEMPLATES = {}

for file in files:
	f = open('synapse/util/watcha_templates/' + file + '.py', 'r')
	TEMPLATES[file] = Template(f.read().decode('utf8'))
	logger.info('load template %s', file)
	f.close()