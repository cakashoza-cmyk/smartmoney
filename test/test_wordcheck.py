"""Unit tests for the recommendation-word check (Title Case handling)."""
import unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wordcheck import scan


class WordcheckTitleCase(unittest.TestCase):
    def test_title_case_own_wording_is_flagged(self):
        for t in ["Opportunity Radar", "Top Sector Opportunities", "Opportunities In Capital Goods", "An Attractive Valuation", "Investment Opportunity",
                  "Upside Case", "Strong Buy", "Recommended Stocks"]:
            self.assertTrue(scan(t), t)

    def test_lowercase_flagged(self):
        self.assertTrue(scan("this sector is an opportunity"))
        self.assertTrue(scan("stocks look undervalued"))

    def test_fund_names_are_data(self):
        for t in ["Hem Growth Opportunities Fund", "SBI Consumption Opportunities Fund", "PI Opportunities AIF II", "ICICI Prudential India Opportunities Fund - Series 2",
                  "Motilal Oswal Special Opportunities Fund", "NEW HORIZON OPPORTUNITIES MASTER FUND", "Opportunities Fund", "Kotak Special Opportunities Master Fund"]:
            self.assertEqual(scan(t), [], t)

    def test_fund_name_does_not_hide_neighbouring_wording(self):
        self.assertTrue(scan("Opportunity Radar lists SBI Consumption Opportunities Fund"))

    def test_table_cells_with_vehicle_word(self):
        self.assertEqual(scan("\tSchroder International Selection Fund Asian Opportunities\tForeign portfolio\t1"), [])
        self.assertTrue(scan("Opportunity Radar\tFinancial Services\t12"))
        self.assertTrue(scan("Sector Opportunities\tFund flows"))  # a vehicle word in a different cell does not exempt

    def test_disclaimer_allowed(self):
        self.assertEqual(scan("Not investment advice and not a recommendation to buy, sell or hold any security."), [])


if __name__ == "__main__":
    unittest.main()
