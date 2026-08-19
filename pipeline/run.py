import os

import config
from app import create_app

app = create_app()

if __name__ == '__main__':
    # Keep the normal local experience aligned with staging: unexpected errors
    # render the friendly global error page. Enable Flask's interactive debugger
    # only when a developer explicitly asks for it.
    debug = (
        config.APP_ENV == 'development'
        and os.environ.get('SEO_COPILOT_DEBUG') == '1'
    )
    app.run(host='0.0.0.0', port=8080, debug=debug)
