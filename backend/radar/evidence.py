"""Shared eligibility rules; plan version alone does not invalidate evidence."""


def current_findings(findings):
    # Steering a URL/query increments plan_version without changing questions.
    # Explicit question/plan revisions mark superseded findings stale instead.
    return [finding for finding in findings if not finding.get('stale') and finding.get('review') != 'rejected']
