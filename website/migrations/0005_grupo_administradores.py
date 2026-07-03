from django.db import migrations


def criar_grupo_administradores(apps, schema_editor):
    """Cria o grupo 'Administradores' e adiciona a ele todos os usuários que
    já possuem perfil Administrador, bem como os superusers existentes."""
    Group = apps.get_model('auth', 'Group')
    User = apps.get_model('auth', 'User')
    Administrador = apps.get_model('website', 'Administrador')

    grupo, _ = Group.objects.get_or_create(name='Administradores')

    ids = set(Administrador.objects.values_list('usuario_id', flat=True))
    ids |= set(User.objects.filter(is_superuser=True).values_list('id', flat=True))

    if ids:
        grupo.user_set.add(*User.objects.filter(id__in=ids))


def remover_grupo_administradores(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name='Administradores').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0004_alter_chacara_num_banheiros_and_more'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(
            criar_grupo_administradores,
            remover_grupo_administradores,
        ),
    ]
