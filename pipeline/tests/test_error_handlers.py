import unittest

from app import create_app


class ErrorHandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)

        @cls.app.route('/_test/unexpected-error', methods=['GET', 'POST'])
        def unexpected_error():
            raise RuntimeError('private implementation detail')

    def setUp(self):
        self.client = self.app.test_client()

    def test_not_found_uses_the_friendly_page(self):
        response = self.client.get('/_test/missing-page')

        self.assertEqual(404, response.status_code)
        self.assertIn(b'We could not find that page', response.data)
        self.assertNotIn(b'Not Found</h1>', response.data)

    def test_unexpected_browser_error_hides_the_exception_detail(self):
        response = self.client.get('/_test/unexpected-error')

        self.assertEqual(500, response.status_code)
        self.assertIn(b'We hit an unexpected problem', response.data)
        self.assertIn(b'Reference code', response.data)
        self.assertNotIn(b'private implementation detail', response.data)

    def test_unexpected_json_error_is_structured_and_safe(self):
        response = self.client.post(
            '/_test/unexpected-error',
            json={},
        )

        self.assertEqual(500, response.status_code)
        self.assertEqual(500, response.json['status'])
        self.assertIn('reference_id', response.json)
        self.assertNotIn('private implementation detail', response.json['error'])


if __name__ == '__main__':
    unittest.main()
