import sys, phonesim as ps
for pol in sys.argv[1:]:
    r = ps.run(pol, n_phones=1000); r.pop('timeline')
    print(pol, {k: (round(v,3) if isinstance(v,float) else v) for k,v in r.items() if k not in ('policy','seed')})
