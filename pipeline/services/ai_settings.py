import config
from app.models import AISetting, ProjectAISetting, db


DEFAULT_SYSTEM_PROMPT = "You are an expert SEO Copilot."


def get_global_ai_setting():
    setting = AISetting.query.first()
    if not setting:
        setting = AISetting(
            model_name=config.OPENROUTER_MODEL or "z-ai/glm-5.2",
            system_prompt=DEFAULT_SYSTEM_PROMPT,
        )
        db.session.add(setting)
        db.session.commit()
    return setting


def get_effective_ai_settings(client_id):
    global_setting = get_global_ai_setting()
    project_setting = ProjectAISetting.query.filter_by(client_id=client_id).first()

    model_name = global_setting.model_name or config.OPENROUTER_MODEL or "z-ai/glm-5.2"
    system_prompt = global_setting.system_prompt or DEFAULT_SYSTEM_PROMPT
    source = "global"

    if project_setting:
        if project_setting.model_name:
            model_name = project_setting.model_name
            source = "project"
        if project_setting.system_prompt:
            system_prompt = project_setting.system_prompt
            source = "project"

    return {
        "model_name": model_name,
        "system_prompt": system_prompt,
        "source": source,
        "project_setting": project_setting,
        "global_setting": global_setting,
    }
