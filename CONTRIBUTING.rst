============
Contributing
============

Contributions are welcome, and are greatly appreciated! Every little bit helps, and credit will be given. Feel free to `join our Facebook group <https://www.facebook.com/groups/tabbycat.debate/>`_ if you have any questions about how to get started.

Bug reports
===========

Please report bugs by opening a new issue in our `GitHub repository <https://github.com/czlee/tabbycat/issues>`_. It is most helpful if you can include:

- How Tabbycat was installed (on Heroku, locally on OS X, `etc.`)
- Any details about your tournament and setup that might be helpful in troubleshooting
- Detailed steps for how to reproduce the bug

Getting started
===============

- To easily test your changes to Tabbycat you probably want a working :ref:`local install <install-local>` (without using Docker)
- Generally we prefer that features and bug fixes are submitted as pull requests on their own branch (as described in the  `git-flow workflow <http://danielkummer.github.io/git-flow-cheatsheet/>`_). Submitting against `develop` (but not `master`) is fine for small fixes and changes.
- We use Django's testing tools — it would be great if new features came with unit tests
    - A number of our tests use `Selenium <http://selenium-python.readthedocs.io>` and `ChromeDriver <https://sites.google.com/a/chromium.org/chromedriver/>` to simulate in-browser functionality. They will fail if you do not have the Chrome browser installed.
- By default the development server's build process will broadcast livereload events; installing one of their `browser plugins <http://livereload.com/extensions/>`_ can make testing front-end changes easier.

Style guide
===========

For python code, we use `flake8 <http://flake8.readthedocs.io>`_ to check for a non-strict series of style rules. Warnings will trigger a Travis CI build to fail. The entire codebase can be checked by using::

    $ flake8 .

For stylesheets, we use `stylelint <https://stylelint.io>`_ to enforce the `AirBnB CSS styleguide <https://github.com/airbnb/css>`_. The relevant code can be checked by using::

    $ npm run stylelint

For javascript, we use `eslint <http://eslint.org/>` to enforce the `AirBnB javascript  styleguide <https://github.com/airbnb/javascript>`_. The relevant code can be checked by using::

    $ npm run eslint

Versioning convention
=====================

Our convention is to increment the minor version whenever we add new functionality, and to increment the major version whenever

- the database can't be migrated forwards using ``python manage.py migrate --no-input``, or
- there is a major change to how the tournament workflow goes, or
- we make some other change that is, in our opinion, significant enough to warrant a milestone.

Most of the time, we write `data migrations <https://docs.djangoproject.com/en/1.10/topics/migrations/#data-migrations>`_ to allow existing systems to be upgraded easily. However, we don't always support backward database migrations. Our expectation is that long-lived installations keep up with our latest version.

One day, we hope to have a public API in place to facilitate the integration with other debating tournament software, like registration or adjudicator feedback systems. If and when that happens, we'll probably revise this convention to be more in line with `Semantic Versioning <http://semver.org/>`_.

Starting from version 0.7.0, we use code names for versions, being breeds of cats in alphabetical order.

Documentation
=============

Documentation is created using `Sphinx <http://sphinx-doc.org/>`_ and hosted at `Read The Docs <https://readthedocs.org>`_. Pushes to ``develop`` will update the *latest* documentation set, while pushes to ``master`` will update the *stable* documentation set.

To preview the documentation locally, install the docs-specific requirements (from the base folder)::

    $ pip install -r 'docs/requirements.txt'

Then start the server::

    $ sphinx-autobuild docs docs/_build/html --port 7999

You should then be able to preview the docs at `127.0.0.1:7999 <http://127.0.0.1:7999>`_.

Project Structure
=================

- ``bin`` contains a number of convenience scripts for starting/stopping Docker, and the webserver/asset pipeline.
- ``data`` contains the sample data sets and fixtures used to setup demo tournaments and in automated tests respectively
- ``docs`` contains our document source files and images (although some are linked from the root directory)
- ``tabbycat`` is the main directory containing the Django project
    - ``locale`` contains translation strings for shared templates (others are in respective app directories)
    - ``templates`` contains shared html templates, stylesheets, javascript source files, and Vue.js components/mixins.
    - ``utils`` contains shared utilities
    - All other folders are the Django apps that contain specific views, models, and templates for functions such as ``draw`` generation/display, or recording ``results``. Each has sub-folders for tests and templates.
- In the root directory there are a number of files defining our python and javascript dependencies, core configuration files, and key documents like the ``README``

Release Checklist
=================

1. Check that all migrations have been generated and committed into Git
2. Bump version number in ``docs/conf.py``
3. Bump version number and (if applicable) codename in ``tabbycat/settings.py``
4. Update the main ``CHANGELOG.rst`` file
5. Check that the last Travis CI build passed
6. Check that ``deploy_heroku.py`` still works
7. Shift remaining issues from the Github Milestone
8. Create and finish the release branch as per git-flow
9. Ensure the tag is correct (``vX.Y.Z``) and published to GitHub
10. Back-merge ``master`` to the ``kitten`` branch
11. Back-merge ``develop`` to the in-progress feature branches
12. Push ``master`` to the release pipeline repository
13. Issue a formal release with change notes on GitHub
14. Post change notes on the Facebook group
