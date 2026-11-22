"""Connector interfaces for credentialed / paid private-market sources. Each connector declares the credentials it needs
(read from environment variables, never hard-coded). Without credentials it records 'needs_credentials' and does nothing.
To activate one: add the secret in GitHub > Settings > Secrets > Actions, implement fetch() against the vendor's licensed API,
and map rows into transactions (txn_type, evidence_label='REPORTED ANNOUNCEMENT' unless the vendor cites a filing)."""
import os
from common import connect, log_run


class PaidConnector:
    source_id = ""
    env = ()
    docs = ""

    def configured(self):
        return all(os.environ.get(e) for e in self.env)

    def fetch(self, con):  # pragma: no cover - needs a licence
        raise NotImplementedError("Vendor API client not implemented until a licence/credential is available: " + self.docs)


class Tracxn(PaidConnector):
    source_id, env, docs = "tracxn", ("TRACXN_API_KEY",), "https://tracxn.com/api (enterprise plan): funding rounds, investors, acquisitions for private companies"


class VentureIntelligence(PaidConnector):
    source_id, env, docs = "venture_intelligence", ("VI_USERNAME", "VI_PASSWORD"), "Venture Intelligence PE/VC deal database (subscription)"


class VCCEdge(PaidConnector):
    source_id, env, docs = "vccedge", ("VCCEDGE_API_KEY",), "VCCEdge deals and company financials (subscription)"


class MCA21(PaidConnector):
    source_id, env, docs = "mca21", ("MCA_USER", "MCA_PASSWORD"), "MCA21 V3 company master data and filings (login; documents are paid per company)"


CONNECTORS = [Tracxn(), VentureIntelligence(), VCCEdge(), MCA21()]


def register():
    con = connect()
    for c in CONNECTORS:
        if not c.configured():
            con.execute("UPDATE sources SET status='needs_credentials' WHERE source_id=?", (c.source_id,))
    con.commit(); con.close()
