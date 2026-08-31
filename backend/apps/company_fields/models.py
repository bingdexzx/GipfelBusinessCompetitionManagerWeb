"""公司产业字段值模型定义在 apps.companies（CompanyFieldValue）。

本应用 company_fields 复用该模型，无独立模型；读写由
apps.company_fields.views 直接操作 apps.companies.models.CompanyFieldValue。
"""
