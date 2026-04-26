# gen_api — Gemini-powered AI analysis layer
# exposes analyse_findings() which returns per-finding commentary + an overall summary

from .analyser import analyse_findings

__all__ = ["analyse_findings"]
