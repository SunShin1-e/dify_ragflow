"""Patch RAGFlow dify endpoint: use kb.vector_similarity_weight + rerank support."""
with open('/ragflow/api/apps/restful_apis/dify_retrieval_api.py', 'r') as f:
    content = f.read()

old = """        ranks = await settings.retriever.retrieval(
            question,
            embd_mdl,
            kb.tenant_id,
            [kb_id],
            page=1,
            page_size=top,
            similarity_threshold=similarity_threshold,
            vector_similarity_weight=0.3,
            top=top,
            doc_ids=doc_ids,
            rank_feature=label_question(question, [kb])
        )"""

new = """        # Build rerank model if configured in tenant
        rerank_mdl = None
        from api.db.services.user_service import TenantService
        _, tenant = TenantService.get_by_id(kb.tenant_id)
        if tenant and tenant.rerank_id:
            rerank_model_config = get_model_config_from_provider_instance(kb.tenant_id, LLMType.RERANK.value, tenant.rerank_id)
            rerank_mdl = LLMBundle(kb.tenant_id, rerank_model_config)

        ranks = await settings.retriever.retrieval(
            question,
            embd_mdl,
            kb.tenant_id,
            [kb_id],
            page=1,
            page_size=top,
            similarity_threshold=similarity_threshold,
            vector_similarity_weight=kb.vector_similarity_weight,
            top=top,
            doc_ids=doc_ids,
            rerank_mdl=rerank_mdl,
            rank_feature=label_question(question, [kb])
        )"""

if old in content:
    content = content.replace(old, new)
    with open('/ragflow/api/apps/restful_apis/dify_retrieval_api.py', 'w') as f:
        f.write(content)
    print('[patch] dify_retrieval_api.py updated with rerank + dynamic weight')
else:
    print('[patch] already applied or pattern not found')
